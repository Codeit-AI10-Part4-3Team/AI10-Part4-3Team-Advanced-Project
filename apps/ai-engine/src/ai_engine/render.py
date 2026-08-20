"""S6 렌더 이음매 — the one image a finalized session produces.

⚠️ **The stub and the real implementation are two branches of the same function**
(구현_범위 1.1절). Filling in `_render_with_model` is the whole of the real work.

Two properties the stub keeps even though it draws nothing:

- **Lossless WebP.** 검증 1순위 scores the Korean glyphs drawn into the comic, and a lossy
  image would have the scorer measuring compression artefacts instead of the model's
  rendering accuracy. The format is part of the contract, not an implementation detail.
- **The requested size, exactly.** The caller sends `spec`, and the job reports
  `width`/`height` from what came back. A placeholder of a convenient size would make the
  job report a size nobody asked for.
"""

import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PIL import Image, ImageDraw

from ai_engine import render_prompt
from ai_engine.config import Settings
from ai_engine.models import ComicDraft, ImageRenderRequest, ImageSpec, Panel

logger = logging.getLogger(__name__)


class RenderFailedError(RuntimeError):
    """그림을 만들지 못했습니다. 라우트가 503 `UPSTREAM_UNAVAILABLE` 로 바꿉니다.

    ⚠️ 거절과 다릅니다. 거절은 `draft:generate` 쪽의 200 이고, 이것은 "지금 이 서비스로는
    안 된다" 입니다. 호출자에게 폴백은 없습니다 - 카피와 그림은 제품마다 달라 사전 승인된
    응답이 성립하지 않습니다 (ADR-0005).
    """


STUB_BACKGROUND = (238, 238, 244)
STUB_FOREGROUND = (120, 120, 140)

PANEL_COLS = 3
PANEL_ROWS = 2
"""만화형 격자 (생성_파이프라인 6절). 칸 수 6 은 계약의 `ComicDraft.panels` 가 강제합니다.

⚠️ **칸의 픽셀 크기는 여기 없습니다.** `spec` 을 이 격자로 나눠 얻습니다 - 1152 를 상수로
적어 두면 기획서 10.2 의 숫자가 계약과 여기 두 곳에 생기고, 호출자가 다른 크기를 보내는 순간
조용히 어긋납니다 (`ImageSpec` 이 유도되지 않는 것과 같은 이유).
"""

COMPOSE_BACKGROUND = (255, 255, 255)
"""칸이 캔버스를 빈틈없이 덮으므로 보일 일이 없습니다. 그래도 흰색인 이유는, 보인다면 그것이
합성이 어긋났다는 신호이고 흰 띠가 검은 띠보다 눈에 띄기 때문입니다."""


def render_image(request: ImageRenderRequest, settings: Settings) -> bytes:
    """Return the finished image as lossless WebP bytes.

    Bytes, not a path: if this service decided where the file lives, the two apps would
    share a filesystem and the coupling would have escaped the HTTP contract (AGENTS.md).
    """
    logger.info(
        "image:render mode=%s outputType=%s spec=%dx%d quality=%s",
        settings.generation_mode,
        request.output_type,
        request.spec.width,
        request.spec.height,
        request.quality,
    )
    if settings.generation_mode == "stub":
        return _render_stub(request, settings)
    return _render_with_model(request, settings)


def _render_stub(request: ImageRenderRequest, settings: Settings) -> bytes:
    """A placeholder that cannot be mistaken for output.

    It says so on its face. A blank or pretty placeholder ends up pasted into a report as a
    result, which is the accident 구현_범위 1.1절 warns about.
    """
    width, height = request.spec.width, request.spec.height
    canvas = Image.new("RGB", (width, height), STUB_BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    # Diagonals plus a border: unmistakably a placeholder at any zoom level, and it needs no
    # font file — bundling one just for the stub would ship a licence question with it.
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=STUB_FOREGROUND, width=4)
    draw.line([(0, 0), (width, height)], fill=STUB_FOREGROUND, width=4)
    draw.line([(0, height), (width, 0)], fill=STUB_FOREGROUND, width=4)
    draw.text((16, 16), f"[{settings.stub_marker}] {request.output_type}", fill=STUB_FOREGROUND)

    buffer = io.BytesIO()
    canvas.save(buffer, format="WEBP", lossless=True)
    return buffer.getvalue()


def _render_with_model(request: ImageRenderRequest, settings: Settings) -> bytes:
    """The real render, through the external image API (ADR-0003).

    ⚠️ **No fallback and no placeholder.** Every failure here raises, and the route turns it
    into a 503 the caller has no recovery path for — that is the design (ADR-0005). A
    placeholder returned from this branch would be indistinguishable from a successful
    render in every log, metric and screenshot.

    출력 유형에 따라 호출 수가 다릅니다. 단일 광고형은 1회, 만화형은 **6회** 입니다
    (ADR-0017). 세션당 렌더 1회를 세는 INV-3 은 렌더 요청을 세지 외부 호출을 세지 않으므로
    그대로입니다.
    """
    if not settings.model_api_key:
        raise RenderFailedError(
            "ADGEN_MODEL_API_KEY 가 비어 있습니다. 키 없이 그림을 그릴 수는 없고, "
            "스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절)."
        )

    client = _client(settings)
    quality = _quality(request, settings)
    if isinstance(request.draft, ComicDraft):
        return _render_panels(request, request.draft, settings, client, quality)
    return _to_lossless_webp(_render_one_shot(request, settings, client, quality))


def _client(settings: Settings) -> Any:
    """벤더 클라이언트. **지연 import 를 여기 하나로 모읍니다.**

    ⚠️ `openai` 는 optional extra 라 스텁만 돌리는 CI 와 컨테이너에는 없습니다. 모듈
    최상단에서 import 하면 이 파일을 읽는 것만으로 ImportError 가 나고, 증상은 "스텁 모드인데
    엔진이 기동하지 않는다" 로 보입니다.

    ⚠️ `timeout` 은 **호출 하나**의 상한입니다. 만화형은 1번 칸을 만든 뒤 나머지 다섯을 동시에
    부르므로 최악의 대기가 이 값의 2배까지 늘어납니다 (칸 하나가 실제로 이 상한까지 갔을 때).
    호출자의 `render_timeout_s` 예산과 맞물리는 값이라 이슈 #141 에서 함께 정합니다.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈리는 경로
        raise RenderFailedError(
            "openai 패키지가 없습니다. pip install -e './apps/ai-engine[model]' 로 설치하세요."
        ) from exc
    return OpenAI(api_key=settings.model_api_key, timeout=settings.image_timeout_s)


def _render_one_shot(
    request: ImageRenderRequest, settings: Settings, client: Any, quality: str
) -> bytes:
    """단일 광고형 1장. 칸이 하나뿐이라 합성 단계를 지나지 않습니다 (생성_파이프라인 6절).

    ⚠️ The call shape is the one 검증 1순위 actually got images out of
    (`notebooks/hj/verify01_korean_text_rendering/run_experiment.py`, 2026-08-14): one
    request, `n=1`, inline base64. A URL response is refused rather than downloaded — the
    experiment never exercised that path, so treating it as equivalent would be a guess.
    """
    return _generate(
        client,
        settings,
        prompt=render_prompt.build(request),
        size=f"{request.spec.width}x{request.spec.height}",
        quality=quality,
        reference=None,
    )


def _render_panels(
    request: ImageRenderRequest,
    draft: ComicDraft,
    settings: Settings,
    client: Any,
    quality: str,
) -> bytes:
    """만화형: 칸을 따로 만들어 3x2 로 붙입니다 (ADR-0017).

    한 장에 6칸을 그리게 하는 방식은 **규격이 산술적으로 달성되지 않아** 폐기됐습니다 -
    3456 / 3 = 1152 는 경계선과 바깥 여백이 0 일 때만 성립하는데, 경계선을 그리라고 지시한
    이상 칸은 반드시 그보다 작아집니다 (실측 1101 ~ 1142px, 여백 14 ~ 36px).

    **1번 칸을 먼저 만들고 2 ~ 6번을 동시에 부릅니다.** 순서가 아니라 의존이 이유입니다 -
    2 ~ 6번은 서로가 아니라 전부 1번 칸만 레퍼런스로 쓰므로 칸끼리 의존이 없습니다. 직전 칸을
    레퍼런스로 넘기는 방식은 이 성질을 깨서 병렬과 배타이고, ADR-0017 이 함께 쓰지 않기로
    했습니다.

    | | 순차 | 병렬 |
    |---|---|---|
    | `medium` 한 세트 | 310.8초 (`render_timeout_s` 300초 초과) | 102.6 ~ 139.2초 |

    호출 수와 비용은 두 방식이 같습니다. 줄어드는 것은 대기 시간뿐입니다.
    """
    panel_size = _panel_size(request.spec)
    size = f"{panel_size[0]}x{panel_size[1]}"
    panels = sorted(draft.panels, key=lambda panel: panel.index)
    logger.info("만화형 컷별 생성: %d칸 %s (1번 뒤 %d건 동시)", len(panels), size, len(panels) - 1)

    def draw(panel: Panel, reference: bytes | None) -> bytes:
        return _generate(
            client,
            settings,
            prompt=render_prompt.build_panel(request, panel, with_reference=reference is not None),
            size=size,
            quality=quality,
            reference=reference,
        )

    head, rest = panels[0], panels[1:]
    # ⚠️ 1번 칸의 크기는 **부채꼴로 퍼지기 전에** 봅니다. 이 칸은 나머지 다섯의 레퍼런스라,
    # 어긋난 채로 넘어가면 잘못된 크기가 다섯 호출의 입력이 되고 그 요금이 다 나간 뒤에야
    # 합성 단계에서 걸립니다.
    first = _as_png(draw(head, None), panel_size)

    # 네트워크 대기가 지배적이라 스레드로 충분합니다. GIL 은 문제가 되지 않습니다.
    #
    # ⚠️ **잡 하나 안에서만 동시입니다.** 잡끼리는 여전히 직렬 1건이고 그것은 호출자의
    # `jobs.next_queued` 가 강제합니다 (ADR-0015). 두 층을 섞으면 동시 외부 호출이 잡 수만큼
    # 곱해집니다.
    with ThreadPoolExecutor(max_workers=len(rest)) as pool:
        pending = [(panel, pool.submit(draw, panel, first)) for panel in rest]
        tiles = [first]
        for panel, future in pending:
            try:
                tiles.append(future.result())
            except RenderFailedError as exc:
                # A3 / N20-a. **한 칸이라도 실패하면 세트 전체가 실패입니다.** 부분 재시도는
                # 열지 않습니다 (ADR-0017) - 불완전한 세트를 내보내는 것보다 명시적으로
                # 실패하는 편이 낫고, 이는 열화를 브리프 자동 채움 하나로 한정한 ADR-0005 와
                # 같은 방향입니다. 이미 나간 다른 칸의 요금은 돌아오지 않습니다.
                raise RenderFailedError(
                    f"{panel.index}번 칸이 실패해 세트 전체를 버립니다: {exc}"
                ) from exc

    return _compose(tiles, panel_size, request.spec)


def _panel_size(spec: ImageSpec) -> tuple[int, int]:
    """칸 하나의 픽셀 크기. **호출자가 보낸 캔버스를 격자로 나눠 얻습니다.**

    ⚠️ 1152 를 상수로 두지 않는 이유는 `ImageSpec` 을 유도하지 않는 이유와 같습니다 - 같은
    숫자가 계약과 구현 두 곳에 생기면 한쪽만 고치는 순간 어긋납니다 (미결정_대장 N16).

    나누어떨어지지 않으면 여기서 멈춥니다. 그대로 진행하면 반올림한 만큼 캔버스에 띠가
    남는데, 그것이 바로 이 방식으로 없앤 "회차마다 흔들리는 여백" 입니다.
    """
    width, height = spec.width // PANEL_COLS, spec.height // PANEL_ROWS
    if width * PANEL_COLS != spec.width or height * PANEL_ROWS != spec.height:
        raise RenderFailedError(
            f"{spec.width}x{spec.height} 는 {PANEL_COLS}x{PANEL_ROWS} 격자로 "
            "나누어떨어지지 않습니다. 만화형 캔버스는 칸의 정수배여야 합니다 "
            "(생성_파이프라인 6절: 3456x2304)."
        )
    if width % 16 or height % 16:
        # 벤더 제약(가로 세로 모두 16의 배수). 여기서 막지 않으면 6회 중 첫 호출이 400 으로
        # 돌아오는데, 그때는 이미 요금이 나간 뒤입니다.
        raise RenderFailedError(
            f"칸 크기 {width}x{height} 가 16의 배수가 아닙니다 (gpt-image-2 제약)."
        )
    return width, height


def _generate(
    client: Any,
    settings: Settings,
    *,
    prompt: str,
    size: str,
    quality: str,
    reference: bytes | None,
) -> bytes:
    """외부 API 호출 1회. 레퍼런스가 있으면 `images.edit`, 없으면 `images.generate`.

    두 경로 모두 검증 1순위가 실제로 이미지를 받아낸 모양입니다 (`run_panels.py`, 2026-08-20
    기준 42회). 인자를 바꾸면 그 실측치가 이전되지 않습니다.
    """
    kwargs: dict[str, Any] = {
        "model": settings.image_model,
        "prompt": prompt,
        "size": size,
        "n": 1,
        "quality": quality,
    }

    try:
        if reference is None:
            response = client.images.generate(**kwargs)
        else:
            # ⚠️ 스레드마다 **새 튜플**을 만듭니다. 열린 파일 객체 하나를 다섯 스레드가 함께
            # 읽으면 읽기 위치가 섞여 본문이 깨집니다 - 실험 하네스는 순차라 이 함정이
            # 드러나지 않았습니다. 바이트를 그대로 넘기면 SDK 가 각자 감쌉니다.
            response = client.images.edit(image=[("panel.png", reference, "image/png")], **kwargs)
    except Exception as exc:
        # 벤더 예외 계층에 의존하지 않습니다.
        # 인증 실패도 쿼터 초과도 타임아웃도 호출자에게는 같은 답입니다: 쓸 수 없음.
        # 벤더의 예외 클래스를 나눠 잡으면 SDK 버전이 오를 때 조용히 빠지는 갈래가 생깁니다.
        raise RenderFailedError(f"{type(exc).__name__}: {exc}") from exc

    return _inline_bytes(response)


def _as_png(payload: bytes, panel_size: tuple[int, int]) -> bytes:
    """레퍼런스로 넘길 1번 칸을 검사하고 PNG 로 맞춥니다.

    `images.edit` 에 형식을 선언해서 보내는데, 벤더가 무엇을 돌려주는지는 우리가 정하는 값이
    아닙니다. 선언과 내용이 다르면 5건이 한꺼번에 400 으로 돌아옵니다. PNG 는 무손실이라 이
    한 번의 재인코딩이 1번 칸의 픽셀을 바꾸지 않습니다 - 그 칸도 최종 합성에 그대로 들어가므로
    손실 압축을 끼워 넣을 수 없는 자리입니다.

    크기 검사가 여기 있는 이유는 **돈입니다.** 합성 단계에서도 같은 검사를 하지만, 그때는 이미
    다섯 칸의 요금이 나간 뒤입니다.
    """
    try:
        with Image.open(io.BytesIO(payload)) as image:
            _check_panel_size(1, image.size, panel_size)
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
    except OSError as exc:
        raise RenderFailedError(f"1번 칸 이미지를 읽지 못했습니다: {exc}") from exc
    return buffer.getvalue()


def _check_panel_size(index: int, got: tuple[int, int], want: tuple[int, int]) -> None:
    """⚠️ **어긋난 칸은 늘려 붙이지 않고 세트를 실패시킵니다** (PR #150 리뷰, 임동규).

    보정하면 캔버스는 3456 x 2304 로 맞아 떨어지지만 그 정확도는 우리 `resize` 가 만든 것이지
    생성 결과가 아닙니다. 재보는 쪽은 합성물의 픽셀을 재므로 **규격 위반이 통과로 보입니다.**
    게다가 재샘플링은 칸에 그려진 한글을 뭉개는데, 검증 1순위가 채점하는 대상이 바로 그
    글자입니다 - 무손실 WebP 를 고집하는 이유와 같은 이유로 여기서 리샘플링을 허용할 수
    없습니다. 렌더에 폴백이 없다는 ADR-0005 와도 같은 방향입니다.
    """
    if got == want:
        return
    raise RenderFailedError(
        f"{index}번 칸이 {got[0]}x{got[1]} 로 왔습니다. 요청은 {want[0]}x{want[1]} 였습니다. "
        "늘려 붙이면 규격 위반이 합성물에서는 통과로 보이므로 세트를 버립니다."
    )


def _compose(tiles: list[bytes], panel_size: tuple[int, int], spec: ImageSpec) -> bytes:
    """칸 6장을 3x2 로 붙여 무손실 WebP 로 내보냅니다.

    읽는 순서대로 왼쪽 위에서 오른쪽으로 채웁니다 (계약 `Panel.index` 가 배치 위치와 1:1).

    **경계선과 바깥 여백은 0px 이고, 그것이 이 방식을 택한 이유입니다.** 여백을 합성 단계가
    결정하므로 회차 편차가 존재하지 않고, 고정 좌표 크롭이 성립합니다 - 인스타그램 그리드로
    자를 때 칸이 어긋나지 않습니다.

    크기가 어긋난 칸은 `_check_panel_size` 가 여기서 세트째 버립니다. 1번 칸은 부채꼴로
    퍼지기 전에 이미 한 번 걸러졌고, 나머지 다섯이 여기서 걸립니다.
    """
    panel_width, panel_height = panel_size
    canvas = Image.new("RGB", (spec.width, spec.height), COMPOSE_BACKGROUND)
    try:
        for index, payload in enumerate(tiles):
            with Image.open(io.BytesIO(payload)) as tile:
                image = tile.convert("RGB")
                _check_panel_size(index + 1, image.size, panel_size)
                canvas.paste(
                    image,
                    ((index % PANEL_COLS) * panel_width, (index // PANEL_COLS) * panel_height),
                )
        buffer = io.BytesIO()
        canvas.save(buffer, format="WEBP", lossless=True)
    except OSError as exc:
        raise RenderFailedError(f"칸을 합성하지 못했습니다: {exc}") from exc
    return buffer.getvalue()


def _quality(request: ImageRenderRequest, settings: Settings) -> str:
    """어느 품질 티어로 부를지. 평소에는 **요청이 정합니다** (계약 `ImageQuality`).

    호출자가 출력 유형을 보고 정해 보내는 값이고, 이 서비스는 유형에서 유도하지 않습니다 -
    `spec` 을 유도하지 않는 것과 같은 이유입니다 (미결정_대장 E-2, 2026-08-20).

    ⚠️ **override 가 채워져 있으면 그것이 이기고, 그때마다 경고를 남깁니다.** 개발과 검증
    실험을 `low` 로 돌리기 위한 스위치인데(생성_파이프라인 6.2절), 조용히 동작하면 그 상태로
    잰 숫자가 운영 경로의 숫자로 보고됩니다. 값 검증은 하지 않습니다 - 벤더가 티어 이름을
    늘렸을 때 실험을 막지 않기 위해서이고, 틀린 값은 API 가 400 으로 즉시 알려 줍니다.
    """
    override = settings.image_quality_override
    if not override:
        return request.quality
    logger.warning(
        "ADGEN_IMAGE_QUALITY_OVERRIDE=%s 가 요청의 티어 %s 를 덮어씁니다. "
        "개발용 스위치이며, 이 상태의 결과는 운영 경로의 것이 아닙니다.",
        override,
        request.quality,
    )
    return override


def _inline_bytes(response: Any) -> bytes:
    """응답에서 이미지 바이트를 꺼냅니다. 인라인 base64 만 다룹니다.

    ⚠️ **응답의 모양을 신뢰하지 않습니다.** 여기서 다루는 것은 우리 자료구조가 아니라 벤더가
    돌려준 객체이고, 세 군데가 각각 다른 이유로 어긋날 수 있습니다 - `data` 가 비었거나
    (`IndexError`), 아예 없거나 (`TypeError`), `b64_json` 이 해독되지 않거나
    (`binascii.Error`). 셋 다 `RenderFailedError` 가 아니므로 라우트의 503 매핑을 지나쳐
    **500 으로 나갑니다** - 계약이 이 경로에 준 실패 코드는 503 하나뿐인데 말입니다
    (2026-08-18 실측).

    ⚠️ 여기서 나가는 실패는 전부 "벤더 응답이 예상과 다르다"입니다. 그래서 호출부를 통째로
    `except Exception` 으로 감싸지 않았습니다 - 그렇게 하면 우리 코드의 결함까지 같은
    503 이 되어, 고칠 수 있는 버그가 남의 서비스 장애로 보고됩니다.
    """
    data = getattr(response, "data", None)
    if not data:
        raise RenderFailedError(
            "응답에 이미지가 없습니다 (data 가 비어 있거나 없음). 요청은 n=1 이므로 "
            "성공 응답이라면 항상 한 장이 실려 있어야 합니다."
        )

    payload = data[0]
    encoded = getattr(payload, "b64_json", None)
    if not encoded:
        raise RenderFailedError(
            "응답에 b64_json 이 없습니다. URL 응답이면 내려받는 경로를 따로 만들어야 하며, "
            "검증 1순위가 그 경로를 확인한 적이 없습니다."
        )

    try:
        return base64.b64decode(encoded)
    except (ValueError, TypeError) as exc:
        # `binascii.Error` 는 `ValueError` 의 하위 클래스입니다. `TypeError` 는 `b64_json` 이
        # 문자열이 아닌 경우로, 위의 `if not encoded` 를 통과한 뒤에도 남아 있는 갈래입니다.
        #
        # ⚠️ `validate=True` 를 주지 않습니다. 기본값은 base64 알파벳이 아닌 문자를 버리므로
        # 줄바꿈이 섞인 응답도 해독되는데, 엄격하게 바꾸면 지금 동작하는 응답이 거절될 수
        # 있습니다. 벤더가 무엇을 보내는지는 검증 1순위가 확인한 범위 밖입니다. 버려진
        # 문자 때문에 깨진 바이트는 `_to_lossless_webp` 가 이어서 잡습니다.
        raise RenderFailedError(f"b64_json 을 해독하지 못했습니다: {exc}") from exc


def _to_lossless_webp(payload: bytes) -> bytes:
    """계약이 정한 형식으로 맞춥니다 (무손실 WebP).

    ⚠️ **무손실이라 다시 인코딩해도 픽셀이 바뀌지 않습니다.** 검증 1순위의 지표가 그려진
    한국어 글자라, 손실 압축을 한 번이라도 거치면 채점이 모델의 렌더링 정확도가 아니라 압축
    아티팩트를 재게 됩니다.

    API 가 이미 WebP 를 주더라도 그대로 통과시키지 않습니다 - 무손실인지 손실인지를 바이트만
    보고 단정할 수 없고, 여기서 한 번 맞춰 두면 벤더가 형식을 바꿔도 계약이 흔들리지 않습니다.
    """
    try:
        with Image.open(io.BytesIO(payload)) as image:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="WEBP", lossless=True)
    except OSError as exc:
        raise RenderFailedError(f"응답 이미지를 읽지 못했습니다: {exc}") from exc
    return buffer.getvalue()

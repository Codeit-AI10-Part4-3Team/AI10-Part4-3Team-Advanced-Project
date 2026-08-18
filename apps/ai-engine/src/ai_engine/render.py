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
from typing import Any

from PIL import Image, ImageDraw

from ai_engine import render_prompt
from ai_engine.config import Settings
from ai_engine.models import ImageRenderRequest

logger = logging.getLogger(__name__)


class RenderFailedError(RuntimeError):
    """그림을 만들지 못했습니다. 라우트가 503 `UPSTREAM_UNAVAILABLE` 로 바꿉니다.

    ⚠️ 거절과 다릅니다. 거절은 `draft:generate` 쪽의 200 이고, 이것은 "지금 이 서비스로는
    안 된다" 입니다. 호출자에게 폴백은 없습니다 - 카피와 그림은 제품마다 달라 사전 승인된
    응답이 성립하지 않습니다 (ADR-0005).
    """


STUB_BACKGROUND = (238, 238, 244)
STUB_FOREGROUND = (120, 120, 140)


def render_image(request: ImageRenderRequest, settings: Settings) -> bytes:
    """Return the finished image as lossless WebP bytes.

    Bytes, not a path: if this service decided where the file lives, the two apps would
    share a filesystem and the coupling would have escaped the HTTP contract (AGENTS.md).
    """
    logger.info(
        "image:render mode=%s outputType=%s spec=%dx%d",
        settings.generation_mode,
        request.output_type,
        request.spec.width,
        request.spec.height,
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

    ⚠️ The call shape is the one 검증 1순위 actually got images out of
    (`notebooks/hj/verify01_korean_text_rendering/run_experiment.py`, 2026-08-14): one
    request, `n=1`, inline base64. A URL response is refused rather than downloaded — the
    experiment never exercised that path, so treating it as equivalent would be a guess.
    """
    if not settings.model_api_key:
        raise RenderFailedError(
            "ADGEN_MODEL_API_KEY 가 비어 있습니다. 키 없이 그림을 그릴 수는 없고, "
            "스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절)."
        )

    prompt = render_prompt.build(request)
    size = f"{request.spec.width}x{request.spec.height}"

    # ⚠️ 지연 import. `openai` 는 optional extra 라 스텁만 돌리는 CI 와 컨테이너에는 없습니다.
    # 모듈 최상단에서 import 하면 이 파일을 읽는 것만으로 ImportError 가 나고, 증상은
    # "스텁 모드인데 엔진이 기동하지 않는다" 로 보입니다.
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈리는 경로
        raise RenderFailedError(
            "openai 패키지가 없습니다. pip install -e './apps/ai-engine[model]' 로 설치하세요."
        ) from exc

    client = OpenAI(api_key=settings.model_api_key, timeout=settings.image_timeout_s)
    kwargs: dict[str, Any] = {"model": settings.image_model, "prompt": prompt, "size": size, "n": 1}
    if settings.image_quality:
        kwargs["quality"] = settings.image_quality

    try:
        response = client.images.generate(**kwargs)
    except Exception as exc:
        # 벤더 예외 계층에 의존하지 않습니다.
        # 인증 실패도 쿼터 초과도 타임아웃도 호출자에게는 같은 답입니다: 쓸 수 없음.
        # 벤더의 예외 클래스를 나눠 잡으면 SDK 버전이 오를 때 조용히 빠지는 갈래가 생깁니다.
        raise RenderFailedError(f"{type(exc).__name__}: {exc}") from exc

    return _to_lossless_webp(_inline_bytes(response))


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

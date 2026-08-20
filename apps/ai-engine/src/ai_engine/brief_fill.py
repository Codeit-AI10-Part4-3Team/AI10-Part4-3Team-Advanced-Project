"""S3 브리프 채우기 이음매 — category / target inference.

⚠️ **The stub and the real implementation are two branches of the same function**, not two
functions and not two routes (구현_범위 1.1절). Filling in `_infer_with_model` is the whole
of the real work; the caller and the contract do not move. Building the real path beside
this one would let the skeleton's guarantees (fallback, guardrail, contract) quietly lapse.

This is the **only** seam with a fallback, and the fallback lives in the caller rather than
here: if this call fails or overruns 15s, apps/backend skips auto-fill and proceeds with
`messageMode: degraded` (ADR-0005). So this module never invents a value to stay alive —
failing loudly is what lets the caller degrade honestly.
"""

import base64
import json
import logging
from typing import Any

from ai_engine import brief_prompt
from ai_engine.config import GenerationMode, Settings
from ai_engine.models import BriefFillResponse, NeedsInput
from ai_engine.service_schemas import BriefFillRequest

logger = logging.getLogger(__name__)


class BriefFillFailedError(RuntimeError):
    """추론을 돌리지 못했습니다. 라우트가 503 `UPSTREAM_UNAVAILABLE` 로 바꿉니다.

    ⚠️ **`needsInput` 과 다릅니다.** 저쪽은 추론이 돌았는데 판단이 서지 않은 것이라 200 이고
    대화의 한 걸음입니다 (API_계약 4절). 이것은 "지금 이 서비스로는 안 된다" 이고, 호출자는
    자동 채움을 건너뛴 뒤 `messageMode: degraded` 로 진행합니다 (ADR-0005).

    ⚠️ 그 열화는 **호출자가** 합니다. 이 모듈이 대신 그럴듯한 값을 만들어 살아남으면, 지어낸
    카테고리가 브리프에 저장되어 나중에 카피의 근거처럼 읽힙니다. 크게 실패하는 것이 호출자가
    정직하게 열화할 수 있게 하는 유일한 방법입니다.
    """


STUB_CATEGORY = "생활용품"
STUB_TARGET = "30대 1인 가구"
"""Fixed values. Not plausible-looking guesses on purpose.

A stub that returns something convincing is a stub that ends up in a report as a
measurement. The mode is logged on every call for the same reason.
"""


def fill_brief(request: BriefFillRequest, settings: Settings) -> BriefFillResponse:
    """Infer `category` and `target` from the product photo and text.

    Returns 200 with `needsInput` rather than an error when inference cannot decide — that
    is a step in the conversation, not a failure (API_계약.md 4절). The stub never takes
    that branch: it always decides, so the skeleton exercises the straight path.
    """
    logger.info("brief:fill mode=%s product=%s", settings.generation_mode, request.product_name)
    if settings.generation_mode == "stub":
        return _infer_stub(request, settings)
    return _infer_with_model(request, settings)


def _infer_stub(_request: BriefFillRequest, settings: Settings) -> BriefFillResponse:
    """Fixed answer, marked as such.

    The request is unused and the underscore says so. The parameter stays because the two
    branches must keep the same signature — that is what lets the real implementation drop
    in without touching the caller (구현_범위 1.1절).
    """
    return BriefFillResponse(
        category=f"[{settings.stub_marker}] {STUB_CATEGORY}",
        target=f"[{settings.stub_marker}] {STUB_TARGET}",
    )


NEEDS_INPUT_FIELD = "note"
"""판단이 서지 않을 때 채워 달라고 요구하는 필드. **모델에게 묻지 않고 코드가 정합니다.**

기획서 9.3 이 정한 회복 경로가 자유 메모 하나이기 때문입니다 (`PATCH .../brief` 로 메모를
채우면 다시 추론). 모델이 필드 이름을 고르게 두면 화면이 매핑할 수 없는 이름 - 그것도 회차마다
다른 이름 - 이 계약을 타고 나갑니다.
"""

MAX_IMAGE_BYTES = 10 * 1024 * 1024
"""계약의 `SessionCreateRequest.productImage` 가 정한 10MB.

⚠️ 호출자가 이미 검사한 값을 다시 봅니다. 중복이지만 **여기서 크기를 재지 않으면 상한을
넘는 사진이 그대로 벤더에게 올라가고**, 그 실패는 요금이 나간 뒤에 옵니다.
"""

_MAGIC: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",
}
"""바이트에서 형식을 알아냅니다. 계약이 받는 세 가지뿐입니다 (GIF 와 HEIC 는 거절).

⚠️ **`Content-Type` 헤더도 파일 이름도 보지 않습니다.** 둘 다 호출자가 실어 보내는 값이라
믿으면 형식 검사가 아무것도 검사하지 않게 됩니다 - backend 의 `backend_core.images` 가 같은
이유로 같은 방식을 씁니다. 그쪽을 import 하지 않는 것은 두 앱의 경계 때문이며 (AGENTS.md),
세 줄짜리 표를 공유하려고 그 선을 넘을 이유는 없습니다.
"""


def _infer_with_model(request: BriefFillRequest, settings: Settings) -> BriefFillResponse:
    """The real inference, through the vendor's text model (기획서 13.2).

    ⚠️ **폴백도 자리표시자도 없습니다.** 여기서 나가는 모든 실패는 `BriefFillFailedError` 이고,
    라우트가 503 으로 바꿉니다. 그럴듯한 기본값을 돌려주는 갈래는 로그에서도 지표에서도 성공한
    추론과 구별되지 않습니다.

    호출 모양은 `render._render_with_model` 을 그대로 따릅니다 - 지연 import, 벤더 예외를
    나눠 잡지 않기, 응답의 모양을 믿지 않기.
    """
    if not settings.model_api_key:
        raise BriefFillFailedError(
            "ADGEN_MODEL_API_KEY 가 비어 있습니다. 키 없이 사진을 읽을 수는 없고, "
            "스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절)."
        )

    image_url = _data_url(_image_bytes(request))
    user_text = brief_prompt.build_user(request.product_name, request.selling_point, request.note)
    logger.info("brief:fill prompt=%s model=%s", brief_prompt.VERSION, settings.text_model)

    # ⚠️ 지연 import. `openai` 는 optional extra 라 스텁만 돌리는 CI 와 컨테이너에는 없습니다.
    # 모듈 최상단에서 import 하면 이 파일을 읽는 것만으로 ImportError 가 나고, 증상은
    # "스텁 모드인데 엔진이 기동하지 않는다" 로 보입니다 (`render` 와 같은 이유, 같은 모양).
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈리는 경로
        raise BriefFillFailedError(
            "openai 패키지가 없습니다. pip install -e './apps/ai-engine[model]' 로 설치하세요."
        ) from exc

    client = OpenAI(api_key=settings.model_api_key, timeout=settings.brief_fill_model_timeout_s)
    try:
        response = client.chat.completions.create(
            model=settings.text_model,
            messages=[
                {"role": "system", "content": brief_prompt.SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            response_format={"type": "json_object"},
            n=1,
        )
    except Exception as exc:
        # 벤더 예외 계층에 의존하지 않습니다. 인증 실패도 쿼터 초과도 타임아웃도 호출자에게는
        # 같은 답입니다: 쓸 수 없음 (`render._render_with_model` 의 같은 판단).
        raise BriefFillFailedError(f"{type(exc).__name__}: {exc}") from exc

    return _to_response(_decode(_content(response)))


def _image_bytes(request: BriefFillRequest) -> bytes:
    """업로드 파일을 바이트로. 동기 파일 객체를 씁니다.

    ⚠️ `await request.product_image.read()` 가 아니라 `.file.read()` 입니다. 이 함수는 동기
    라우트에서 불리고 (FastAPI 가 스레드풀로 보냅니다), 여기서 코루틴을 만들면 아무도 기다리지
    않아 빈 바이트가 조용히 올라갑니다.
    """
    upload = request.product_image
    if upload is None:
        raise BriefFillFailedError("productImage 가 없습니다. 사진 없이 추론할 수 없습니다.")
    try:
        payload = upload.file.read()
    except OSError as exc:
        raise BriefFillFailedError(f"업로드 파일을 읽지 못했습니다: {exc}") from exc
    if not payload:
        raise BriefFillFailedError("productImage 가 비어 있습니다.")
    if len(payload) > MAX_IMAGE_BYTES:
        raise BriefFillFailedError(
            f"productImage 가 {len(payload)} 바이트로 상한 {MAX_IMAGE_BYTES} 를 넘습니다."
        )
    return payload


def _data_url(payload: bytes) -> str:
    """벤더에게 넘길 인라인 이미지. 형식은 바이트에서 알아냅니다."""
    for magic, media_type in _MAGIC.items():
        if payload.startswith(magic):
            return f"data:{media_type};base64,{base64.b64encode(payload).decode()}"
    raise BriefFillFailedError(
        "productImage 의 형식을 알 수 없습니다. 계약이 받는 것은 JPEG, PNG, WebP 뿐입니다."
    )


def _content(response: Any) -> str:
    """응답에서 본문을 꺼냅니다.

    ⚠️ **응답의 모양을 신뢰하지 않습니다.** 우리 자료구조가 아니라 벤더가 돌려준 객체이고,
    `choices` 가 비었거나(`IndexError`) 아예 없거나(`TypeError`) `content` 가 `None` 일 수
    있습니다 (거절이나 길이 초과로 끊긴 경우). 셋 다 `BriefFillFailedError` 가 아니면 라우트의
    503 매핑을 지나쳐 **500 으로 나갑니다** - 계약이 이 경로에 준 실패 코드는 503 하나인데도
    말입니다 (`render._inline_bytes` 가 같은 사고로 고쳐진 자리입니다, 2026-08-18).
    """
    choices = getattr(response, "choices", None)
    if not choices:
        raise BriefFillFailedError("응답에 choices 가 없습니다.")
    content = getattr(getattr(choices[0], "message", None), "content", None)
    if not content or not isinstance(content, str):
        raise BriefFillFailedError("응답 본문이 비어 있습니다 (거절이거나 중간에 끊겼습니다).")
    return content


def _decode(body: str) -> dict[str, Any]:
    """JSON 하나를 읽습니다. 못 읽으면 실패이고, 되살리려 들지 않습니다.

    ⚠️ 깨진 JSON 에서 정규식으로 값을 건져 내는 코드를 쓰지 마세요. 그것은 모델이 형식을 지키지
    않았다는 신호를 지우는 일이고, 남는 것은 어쩌다 걸린 문자열입니다.
    """
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise BriefFillFailedError(f"응답이 JSON 이 아닙니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise BriefFillFailedError(f"응답 JSON 이 객체가 아닙니다: {type(payload).__name__}")
    return payload


def _to_response(payload: dict[str, Any]) -> BriefFillResponse:
    """모델의 JSON 을 계약의 응답으로. 두 갈래뿐입니다.

    ⚠️ 거절 갈래에서 `category` 와 `target` 은 **빈 문자열**입니다 (계약 `BriefFillResponse`).
    `null` 이 아닙니다 - 계약에 `null` 은 어디에도 없고, 키를 빼면 필수 필드가 사라집니다.

    ⚠️ **두 갈래 중 어느 쪽도 아닌 응답은 실패입니다.** 반쯤 채워진 답(카테고리만 있고 타겟은
    빈)을 거절로 바꿔 주거나 문구를 대신 지어내면, 모델이 형식을 지키지 않았다는 사실이 지워진
    채 `needsInput` 이 나갑니다 - 그러면 사용자에게 "메모를 더 써 달라" 고 요구해 놓고 정작
    부족했던 것은 우리 쪽 응답 처리가 됩니다.
    """
    needs_input = payload.get("needsInput")
    if isinstance(needs_input, dict):
        reason = needs_input.get("reason")
        if isinstance(reason, str) and reason:
            return BriefFillResponse(
                category="",
                target="",
                needs_input=NeedsInput(field=NEEDS_INPUT_FIELD, reason=reason),
            )
        raise BriefFillFailedError("needsInput 에 사용자에게 보여 줄 reason 이 없습니다.")

    category, target = payload.get("category"), payload.get("target")
    if isinstance(category, str) and isinstance(target, str) and category and target:
        return BriefFillResponse(category=category, target=target)

    raise BriefFillFailedError(f"응답이 결정 형식도 거절 형식도 아닙니다: {sorted(payload)}")


def describe_mode(mode: GenerationMode) -> str:
    """One line for the startup log, so nobody has to read the source to know."""
    return "스텁 고정값" if mode == "stub" else "실모델"

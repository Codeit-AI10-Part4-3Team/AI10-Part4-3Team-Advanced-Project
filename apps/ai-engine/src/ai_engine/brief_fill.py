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

import logging

from ai_engine.config import GenerationMode, Settings
from ai_engine.models import BriefFillResponse
from ai_engine.service_schemas import BriefFillRequest

logger = logging.getLogger(__name__)

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


def _infer_with_model(request: BriefFillRequest, settings: Settings) -> BriefFillResponse:
    """The real inference. Not written yet.

    ⚠️ Raise rather than degrade. A silent fallback here would put an invented category into
    a brief that later becomes the grounding for generated copy.
    """
    raise NotImplementedError(
        f"generation_mode={settings.generation_mode!r} but the model path is not implemented; "
        "set ADGEN_GENERATION_MODE=stub or fill in ai_engine.brief_fill._infer_with_model"
    )


def describe_mode(mode: GenerationMode) -> str:
    """One line for the startup log, so nobody has to read the source to know."""
    return "스텁 고정값" if mode == "stub" else "실모델"

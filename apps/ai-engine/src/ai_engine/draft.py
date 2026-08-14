"""S4 시안 생성 이음매 — the ad plan and copy the user reviews.

⚠️ **The stub and the real implementation are two branches of the same function**
(구현_범위 1.1절). Filling in `_generate_with_model` is the whole of the real work.

Two rules this module must not "simplify":

- **No fallback.** Copy differs per product, so a pre-approved response does not exist.
  When the model call fails this path fails explicitly (ADR-0005). Assembling copy from
  rules instead is exactly how claims the input never made get published.
- **The stub is comic-blind.** Only the single-ad branch is filled, because the walking
  skeleton's single pass-through path is single-ad; the comic branch exists as structure
  and raises (구현_범위 1절). Faking six panels would make the comic path look finished.
"""

import logging

from ai_engine.config import Settings
from ai_engine.models import DraftGenerateRequest, DraftGenerateResponse, SingleAdDraft

logger = logging.getLogger(__name__)


def generate_draft(request: DraftGenerateRequest, settings: Settings) -> DraftGenerateResponse:
    """Write the draft, or refuse.

    A refusal is `draft` omitted with `refusalReason` set — a normal 200, meaning we could
    have written something and declined to invent it.

    `guardrailApplied` is echoed on every response, refusal or not: without it a control run
    and a verified output are indistinguishable and the suppression rate cannot be computed.
    """
    logger.info(
        "draft:generate mode=%s outputType=%s guardrail=%s",
        settings.generation_mode,
        request.output_type,
        request.guardrail_applied,
    )
    if settings.generation_mode == "stub":
        return _generate_stub(request, settings)
    return _generate_with_model(request, settings)


def _generate_stub(request: DraftGenerateRequest, settings: Settings) -> DraftGenerateResponse:
    """Fixed single-ad draft, visibly marked.

    ⚠️ The copy is built **only** from `sellingPoint`, which is the guardrail's evidence
    (`sellingPoint` + `note`). Even a stub must not put a number or a claim on the wire that
    the input did not carry — the skeleton is where that habit is set.
    """
    if request.output_type == "comic":
        raise NotImplementedError(
            "comic output is a structural branch only in the walking skeleton "
            "(구현_범위 1절); the stub fills the single-ad path"
        )

    marker = settings.stub_marker
    brief = request.brief
    return DraftGenerateResponse(
        draft=SingleAdDraft(
            ad_plan=f"[{marker}] {brief.product_name} 광고 기획안. 근거: {brief.selling_point}",
            ad_copy=f"[{marker}] {brief.selling_point}",
            visual_plan=f"[{marker}] {brief.art_style} 화풍의 제품 단독 컷",
        ),
        guardrail_applied=request.guardrail_applied,
    )


def _generate_with_model(
    request: DraftGenerateRequest, settings: Settings
) -> DraftGenerateResponse:
    """The real generation. Not written yet.

    ⚠️ Raise rather than fall back. This seam has no degraded mode by design.
    """
    raise NotImplementedError(
        f"generation_mode={settings.generation_mode!r} but the model path is not implemented; "
        "set ADGEN_GENERATION_MODE=stub or fill in ai_engine.draft._generate_with_model"
    )

"""S4 시안 생성과 S5 부분 교체 이음매 — the ad plan and copy the user reviews.

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
from ai_engine.models import (
    DraftGenerateRequest,
    DraftGenerateResponse,
    DraftPatchEngineRequest,
    SingleAdDraft,
)

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


def patch_draft(request: DraftPatchEngineRequest, settings: Settings) -> DraftGenerateResponse:
    """Rewrite the named parts of an existing draft, and nothing else.

    ⚠️ **The fields outside the patch come back unchanged.** That is the whole difference
    between 부분 교체 and regeneration: a caller that asked to change the copy has a visual
    plan it already approved, and quietly rewriting it discards a decision the user made.
    """
    logger.info(
        "draft:patch mode=%s outputType=%s fields=%s guardrail=%s",
        settings.generation_mode,
        request.output_type,
        sorted(request.patch.model_fields_set),
        request.guardrail_applied,
    )
    if settings.generation_mode == "stub":
        return _patch_stub(request, settings)
    return _patch_with_model(request, settings)


def _patch_stub(request: DraftPatchEngineRequest, settings: Settings) -> DraftGenerateResponse:
    """Apply the patch literally, with the stub marker on what moved.

    ⚠️ **The stub takes the caller's text as given** rather than writing new copy from the
    brief. A patch carries what the user typed, and the one thing this branch can honestly
    do with it is put it where it belongs — inventing replacement copy here would put claims
    on the wire that neither the input nor the user supplied (ADR-0005, INV-6).

    ⚠️ Comic-blind, like `_generate_stub`. The skeleton's pass-through path is single-ad and
    the comic branch exists as structure only (구현_범위 1절); patching six panels here would
    make the comic path look finished.
    """
    if request.output_type == "comic":
        raise NotImplementedError(
            "comic output is a structural branch only in the walking skeleton "
            "(구현_범위 1절); the stub patches the single-ad path"
        )

    marker = settings.stub_marker
    # `exclude_unset` and not `exclude_none`: in this family an omitted key and `""` are
    # opposite instructions — "leave it alone" against "empty it" (models/patch.py).
    # ⚠️ `exclude={"panels"}` is now unreachable — `check_patch_matches_output_type` rejects
    # a single-ad patch that names `panels`. Kept because `model_copy` below does not
    # validate: were the check ever removed, this is what stops a stray key from landing on
    # the draft as an attribute. It must never be the thing deciding the outcome, which is
    # exactly what it was doing before 2026-08-18 (silent 200, draft unchanged).
    changes = {
        name: f"[{marker}] {value}"
        for name, value in request.patch.model_dump(exclude_unset=True, exclude={"panels"}).items()
    }
    return DraftGenerateResponse(
        draft=request.draft.model_copy(update=changes),
        guardrail_applied=request.guardrail_applied,
    )


def _patch_with_model(
    request: DraftPatchEngineRequest, settings: Settings
) -> DraftGenerateResponse:
    """The real partial regeneration. Not written yet.

    ⚠️ Raise rather than fall back, for the same reason as `_generate_with_model`: there is
    no pre-approved copy for a product we have not seen.
    """
    raise NotImplementedError(
        f"generation_mode={settings.generation_mode!r} but the model path is not implemented; "
        "set ADGEN_GENERATION_MODE=stub or fill in ai_engine.draft._patch_with_model"
    )

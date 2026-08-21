"""Wire models for the ad-generation contract (packages/contracts/openapi.yaml).

`from ai_engine.models import X` always gives a **contract** model. That is now the only
kind this package holds: `legacy_qa` — the template's question-and-answer models — was
deleted on 2026-08-20 with the `/v1/generate` route it served. Keeping it out of `__all__`
until then is what made the deletion mechanical, since every call site had to name it.

This package carries only what the internal `generation` paths use. Sessions, jobs, auth,
catalog and `BriefMeta` are the caller's concern and are absent on purpose — copying schemas
this service never receives would create drift with nothing to catch it.

Two exceptions to "all contract schemas live here":

- `BriefFillRequest` is in `ai_engine.service_schemas` (it names an uploaded file).
- The patch family in `ai_engine.models.patch` covers only the **engine side**
  (`DraftPatchEngineRequest` and what it contains). `DraftPatchRequest`, `BriefPatch` and
  `BriefPatchRequest` are the caller's own request bodies and stay absent.
"""

from ai_engine.models.brief import Brief, Character, NeedsInput, check_brief_matches_output_type
from ai_engine.models.common import Base, Error, ErrorCode, Omittable, OutputType
from ai_engine.models.draft import (
    PANEL_ROLES,
    AdPlan,
    ComicDraft,
    Draft,
    Panel,
    PanelRole,
    SingleAdDraft,
    check_draft_matches_output_type,
)
from ai_engine.models.generation import (
    BriefFillResponse,
    DraftGenerateRequest,
    DraftGenerateResponse,
    GuardrailApplied,
    ImageQuality,
    ImageRenderRequest,
    ImageSpec,
    RefusalReason,
)
from ai_engine.models.patch import (
    DraftPatch,
    DraftPatchEngineRequest,
    PanelPatch,
    PanelPatchMap,
    check_patch_matches_output_type,
)

__all__ = [
    "PANEL_ROLES",
    "AdPlan",
    "Base",
    "Brief",
    "BriefFillResponse",
    "Character",
    "ComicDraft",
    "Draft",
    "DraftGenerateRequest",
    "DraftGenerateResponse",
    "DraftPatch",
    "DraftPatchEngineRequest",
    "Error",
    "ErrorCode",
    "GuardrailApplied",
    "ImageQuality",
    "ImageRenderRequest",
    "ImageSpec",
    "NeedsInput",
    "Omittable",
    "OutputType",
    "Panel",
    "PanelPatch",
    "PanelPatchMap",
    "PanelRole",
    "RefusalReason",
    "SingleAdDraft",
    "check_brief_matches_output_type",
    "check_draft_matches_output_type",
    "check_patch_matches_output_type",
]

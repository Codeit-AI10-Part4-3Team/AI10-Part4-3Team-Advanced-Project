"""Wire models for the ad-generation contract (packages/contracts/openapi.yaml).

`from ai_engine.models import X` always gives a **contract** model. The template
question-and-answer models the walking skeleton still runs on are not re-exported here —
import them from `ai_engine.models.legacy_qa`, which makes every remaining call site visible
and the eventual deletion mechanical.

This package carries only what the internal `generation` paths use. Sessions, jobs, auth,
catalog and `BriefMeta` are the caller's concern and are absent on purpose — copying schemas
this service never receives would create drift with nothing to catch it.

Two exceptions to "all contract schemas live here":

- `BriefFillRequest` is in `ai_engine.service_schemas` (it names an uploaded file).
- `DraftPatchEngineRequest` and the patch family are not written yet. They serve 부분 교체,
  which is off the walking skeleton's single pass-through path, so they were deferred to
  land this before the 08-14 관통 deadline. The contract already describes them.
"""

from ai_engine.models.brief import Brief, Character, NeedsInput, check_brief_matches_output_type
from ai_engine.models.common import Base, Error, ErrorCode, Omittable, OutputType
from ai_engine.models.draft import (
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
    ImageRenderRequest,
    ImageSpec,
    RefusalReason,
)

__all__ = [
    "AdPlan",
    "Base",
    "Brief",
    "BriefFillResponse",
    "Character",
    "ComicDraft",
    "Draft",
    "DraftGenerateRequest",
    "DraftGenerateResponse",
    "Error",
    "ErrorCode",
    "GuardrailApplied",
    "ImageRenderRequest",
    "ImageSpec",
    "NeedsInput",
    "Omittable",
    "OutputType",
    "Panel",
    "PanelRole",
    "RefusalReason",
    "SingleAdDraft",
    "check_brief_matches_output_type",
    "check_draft_matches_output_type",
]

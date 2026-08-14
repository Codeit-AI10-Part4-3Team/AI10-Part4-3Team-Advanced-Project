"""Wire models for the ad-generation contract (packages/contracts/openapi.yaml).

`from backend_core.models import X` always gives a **contract** model. The template
question-and-answer models that the walking skeleton still runs on are not re-exported
here — import them from `backend_core.models.legacy_qa`, which makes every remaining call
site visible and the eventual deletion mechanical.

Two contract schemas are **not** here:

- `SessionCreateRequest` is in `api.schemas` — it names an uploaded file, and `backend_core`
  stays importable without a web framework (apps/backend/AGENTS.md).
- The patch family (`BriefPatch`, `DraftPatch`, `PanelPatchMap`, their request wrappers and
  `DraftPatchEngineRequest`) is not written yet. They serve S5 (부분 교체), which is off the
  walking skeleton's single pass-through path, so they were deferred to keep this landing
  before the 08-14 관통 deadline. The contract already describes them.
"""

from backend_core.models.auth import LoginRequest, Me
from backend_core.models.brief import (
    Brief,
    BriefMeta,
    Character,
    FieldMeta,
    FilledBy,
    NeedsInput,
    Visibility,
    check_brief_matches_output_type,
)
from backend_core.models.catalog import ArtStyle, Template
from backend_core.models.common import (
    Base,
    Error,
    ErrorCode,
    MessageMode,
    Omittable,
    OutputType,
)
from backend_core.models.draft import (
    AdPlan,
    ComicDraft,
    Draft,
    Panel,
    PanelRole,
    SingleAdDraft,
    check_draft_matches_output_type,
)
from backend_core.models.generation import (
    BriefFillResponse,
    DraftGenerateRequest,
    DraftGenerateResponse,
    GuardrailApplied,
    ImageRenderRequest,
    ImageSpec,
    RefusalReason,
)
from backend_core.models.job import Job, JobResult, JobStatus
from backend_core.models.session import (
    FinalizeAccepted,
    Session,
    SessionState,
    SessionSummary,
)

__all__ = [
    "AdPlan",
    "ArtStyle",
    "Base",
    "Brief",
    "BriefFillResponse",
    "BriefMeta",
    "Character",
    "ComicDraft",
    "Draft",
    "DraftGenerateRequest",
    "DraftGenerateResponse",
    "Error",
    "ErrorCode",
    "FieldMeta",
    "FilledBy",
    "FinalizeAccepted",
    "GuardrailApplied",
    "ImageRenderRequest",
    "ImageSpec",
    "Job",
    "JobResult",
    "JobStatus",
    "LoginRequest",
    "Me",
    "MessageMode",
    "NeedsInput",
    "Omittable",
    "OutputType",
    "Panel",
    "PanelRole",
    "RefusalReason",
    "Session",
    "SessionState",
    "SessionSummary",
    "SingleAdDraft",
    "Template",
    "Visibility",
    "check_brief_matches_output_type",
    "check_draft_matches_output_type",
]

"""Wire models for the ad-generation contract (packages/contracts/openapi.yaml).

`from backend_core.models import X` always gives a **contract** model. The template
question-and-answer models that the walking skeleton still runs on are not re-exported
here — import them from `backend_core.models.legacy_qa`, which makes every remaining call
site visible and the eventual deletion mechanical.

One contract schema is **not** here: `SessionCreateRequest` lives in `api.schemas`, because
it names an uploaded file and `backend_core` stays importable without a web framework
(apps/backend/AGENTS.md).
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
from backend_core.models.patch import (
    BriefPatch,
    BriefPatchRequest,
    DraftPatch,
    DraftPatchEngineRequest,
    DraftPatchRequest,
    PanelPatch,
    PanelPatchMap,
)
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
    "BriefPatch",
    "BriefPatchRequest",
    "Character",
    "ComicDraft",
    "Draft",
    "DraftGenerateRequest",
    "DraftGenerateResponse",
    "DraftPatch",
    "DraftPatchEngineRequest",
    "DraftPatchRequest",
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
    "PanelPatch",
    "PanelPatchMap",
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

"""Session — one piece of work, from first input to finished file.

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서).

Two one-way doors: the brief locks when draft generation is requested (INV-7), and the
draft locks at finalize (INV-2). A failed generation reopens the first (ADR-0012).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from backend_core.models.brief import Brief, BriefMeta, NeedsInput, check_brief_matches_output_type
from backend_core.models.common import Base, MessageMode, Omittable, OutputType
from backend_core.models.draft import Draft, check_draft_matches_output_type

SessionState = Literal[
    "created",
    "brief_filling",
    "brief_ready",
    "draft_generating",
    "draft_ready",
    "finalized",
    "rendering",
    "completed",
    "failed",
]
"""Contract: `components.schemas.SessionState`. State diagram: 용어_사전.md 3.1절.

⚠️ A different layer from a job's `status`. Success here is `completed`, not `done`.
Nothing leaves `failed` — that session ends and a new one is created.
"""


class SessionSummary(Base):
    """Contract: `components.schemas.SessionSummary`. List view; carries no draft body."""

    session_id: UUID
    state: SessionState
    output_type: OutputType
    product_name: str
    message_mode: MessageMode
    created_at: datetime
    updated_at: datetime


class Session(Base):
    """Contract: `components.schemas.Session`.

    An absent key means "not applicable to this output type" (`aspectRatio` on a comic) or
    "not there yet" (`jobId` before finalize, `draft` before generation). The two are not
    distinguished because the client does the same thing either way, and `state` already
    says which it is.

    ⚠️ **No `userId`, deliberately.** Every session has an owner, but a session that is not
    yours is a 404 (INV-9) — so everything reaching a client is already the requester's, and
    shipping the value would only invite `session.userId === me.userId` checks that are
    always true. Dead code that looks like a security check is worse than none.
    """

    session_id: UUID
    state: SessionState
    output_type: OutputType
    revision: int = Field(ge=0, description="부분 교체마다 1 증가")
    message_mode: MessageMode
    brief: Brief
    brief_meta: BriefMeta
    draft: Omittable[Draft] = None
    needs_input: Omittable[NeedsInput] = None
    job_id: Omittable[str] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _check_output_type_pairing(self) -> "Session":
        """The output type decides which optional fields may exist at all.

        Checked here rather than inside `Brief`/`Draft` because this is the only place that
        holds the output type alongside them.
        """
        check_brief_matches_output_type(self.output_type, self.brief)
        if self.draft is not None:
            check_draft_matches_output_type(self.output_type, self.draft)
        return self


class FinalizeAccepted(Base):
    """Contract: `components.schemas.FinalizeAccepted`. 202 body for `POST .../finalize`."""

    job_id: str
    status_url: str = Field(description="`/v1/jobs/{jobId}`")

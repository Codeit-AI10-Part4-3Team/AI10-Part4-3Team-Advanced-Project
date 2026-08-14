"""The operations a session goes through, as domain functions.

Routers stay thin — validate, call one of these, map the response (apps/backend/AGENTS.md).
Everything that decides *what a session becomes* lives here, so the rules can be read in one
file and tested without a web framework.

Each function takes the current session and returns the next one. Nothing here writes to
storage or reads configuration: the caller does both, which is what keeps these functions
callable from a test with three lines of setup.

⚠️ Every state change goes through `state.require_transition`. Assigning `session.state`
directly anywhere in this file is a bug, even when the assignment happens to be correct —
the guard is what makes INV-2, INV-3 and INV-7 true, and a path that skips it is a path
where they are not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend_core import state
from backend_core.models import (
    Brief,
    BriefFillResponse,
    BriefMeta,
    BriefPatch,
    Draft,
    DraftGenerateResponse,
    FieldMeta,
    FilledBy,
    OutputType,
    Session,
    Visibility,
    check_brief_matches_output_type,
)


@dataclass(frozen=True)
class CreateInput:
    """What the user typed, after validation and after the image is on disk."""

    session_id: UUID
    output_type: OutputType
    product_image_url: str
    product_name: str
    selling_point: str
    note: str
    art_style: str


def _meta(filled_by: FilledBy, visibility: Visibility = "editable") -> FieldMeta:
    return FieldMeta(filled_by=filled_by, visibility=visibility)


def create(user_input: CreateInput, filled: BriefFillResponse | None, at: datetime) -> Session:
    """Build the session that `POST /v1/sessions` answers with.

    `filled` is `None` when the engine could not be reached — **that absence is the degraded
    path** (ADR-0005). The three outcomes the contract describes are decided here:

    | filled | needsInput | state | messageMode |
    |---|---|---|---|
    | 있음 | 없음 | `brief_ready` | `normal` |
    | 있음 | 있음 | `brief_filling` | `normal` |
    | 없음 | - | `brief_filling` | `degraded` |

    ⚠️ The degraded case stops at `brief_filling` rather than continuing to `brief_ready`.
    Moving on would let draft generation start with an empty `category` and `target`, and
    the guardrail's evidence is the brief — a draft built on blanks is the failure ADR-0005
    exists to prevent. Skipping the automation is the only degradation we do; inventing the
    two values would be the other kind, and it is forbidden.
    """
    # ⚠️ `needsInput` is passed as a **key that is either there or not**, never as `None`.
    # `Base` rejects an explicit null in Python construction exactly as it does on the wire
    # (models/common.py `_reject_null`), and that is deliberate: there is no seam between
    # the two, because FastAPI hands pydantic a dict either way.
    absent_or_present = {"needs_input": filled.needs_input} if filled and filled.needs_input else {}
    session = Session(
        session_id=user_input.session_id,
        state="created",
        output_type=user_input.output_type,
        revision=0,
        message_mode="normal" if filled else "degraded",
        brief=Brief(
            product_image_url=user_input.product_image_url,
            product_name=user_input.product_name,
            selling_point=user_input.selling_point,
            note=user_input.note,
            category=filled.category if filled else "",
            target=filled.target if filled else "",
            art_style=user_input.art_style,
        ),
        brief_meta=BriefMeta(
            product_image_url=_meta("user"),
            product_name=_meta("user"),
            selling_point=_meta("user"),
            note=_meta("user"),
            category=_meta("inferred" if filled else "default"),
            target=_meta("inferred" if filled else "default"),
            # ⚠️ `random` when we chose it, `user` when they did. The screen shows the two
            # differently — an auto-picked style has to be visibly changeable (기획서 5.4).
            art_style=_meta("user" if user_input.art_style else "random"),
        ),
        created_at=at,
        updated_at=at,
        **absent_or_present,
    )
    session.state = state.require_transition(session.state, "brief_filling")
    if filled and filled.needs_input is None:
        session.state = state.require_transition(session.state, "brief_ready")
    return session


def apply_draft(session: Session, response: DraftGenerateResponse, at: datetime) -> Session:
    """Land a successful generation on the session.

    Called only when `response.draft` is present. A refusal (`draft` absent) is not a state
    change at all — the route answers 422 and the session stays where the failure left it.
    """
    assert response.draft is not None  # noqa: S101 - callers branch on this first
    session.draft = response.draft
    session.state = state.require_transition(session.state, "draft_ready")
    session.updated_at = at
    return session


def fail_draft(session: Session, at: datetime) -> Session:
    """Generation failed: go back to `brief_ready` and unlock the brief (ADR-0012).

    ⚠️ This edge is the entire reason ADR-0012 exists. Without it a session whose generation
    failed keeps a locked brief and no draft — nothing to correct, and no way to retry. The
    brief is only locked to protect a draft's evidence, and there is no draft.
    """
    session.state = state.require_transition(session.state, "brief_ready")
    session.updated_at = at
    return session


def start_generating(session: Session, at: datetime) -> Session:
    """Enter `draft_generating`, which is what locks the brief (INV-7).

    Refuses with `StateConflictError` from anywhere but `brief_ready` — including a second
    call while the first is still running, and any call after `finalized`.
    """
    session.state = state.require_transition(session.state, "draft_generating")
    session.updated_at = at
    return session


def replace_draft(session: Session, draft: Draft, at: datetime) -> Session:
    """A patched draft. `draft_ready -> draft_ready`, one revision on.

    `revision` counts replacements, not requests: it is what a client compares to know its
    copy is stale, so a request that changed nothing must not move it.
    """
    session.draft = draft
    session.revision += 1
    session.state = state.require_transition(session.state, "draft_ready")
    session.updated_at = at
    return session


class RevisionConflictError(Exception):
    """The client is patching a version of the session it no longer has.

    ⚠️ Optimistic locking, and it is not optional. Two screens open on the same session both
    hold `revision: 3`; without this the second save silently discards the first person's
    edit and neither of them ever finds out.
    """

    def __init__(self, expected: int, sent: int) -> None:
        self.expected = expected
        self.sent = sent
        super().__init__(f"session is at revision {expected}, request carried {sent}")


def require_revision(session: Session, sent: int) -> None:
    """Refuse a patch built on a stale copy. `revision` is a body field, not `If-Match` —
    the contract records why."""
    if session.revision != sent:
        raise RevisionConflictError(session.revision, sent)


def apply_brief_patch(session: Session, patch: BriefPatch, at: datetime) -> Session:
    """Merge the named brief fields and re-decide the state.

    ⚠️ Read with `exclude_unset`, which is the only correct way to read this family: an
    omitted key means "leave it alone" and `""` means "empty it", and they are opposite
    instructions. `exclude_none` would treat both as absent and quietly ignore every
    request to clear a field.

    Every field the user touches has its `filledBy` flipped to `user`, including one that
    was `inferred` a moment ago — 기획서 5.4 requires an auto-filled value to be visibly
    correctable, and a value the person just typed is no longer the model's guess.
    """
    changes = patch.model_dump(exclude_unset=True)
    brief = session.brief.model_copy(update=changes)
    check_brief_matches_output_type(session.output_type, brief)

    # `BriefMeta` carries exactly `Brief`'s keys — a conformance test enforces it — so every
    # changed field names a meta field, with no lookup needed to find out.
    meta = session.brief_meta.model_copy(update={field: _meta("user") for field in changes})
    return replace_brief(session, brief, meta, at)


def replace_brief(session: Session, brief: Brief, meta: BriefMeta, at: datetime) -> Session:
    """A patched brief, and the state it lands in.

    From `brief_filling` this is the answer to `needsInput` or to a degraded session: it
    reaches `brief_ready` once `category` and `target` are both filled, and stays in
    `brief_filling` otherwise, because those two are what draft generation needs.

    ⚠️ **The target is always a brief-editing state — never `session.state`.** That is the
    whole of INV-7 on this path, and getting it wrong does not look wrong:
    `draft_ready -> draft_ready` is a legal edge (draft patches repeat), so targeting "wherever
    we already are" made the guard vacuous. A brief patch that left the brief *incomplete*
    then landed with a **200 while a draft existed**, overwriting the evidence that draft was
    built on (2026-08-14 실측 — 기존 테스트는 완성된 patch 만 보내고 있어 이 구멍을 지나쳤습니다).

    Both targets below are unreachable from anywhere a draft exists, so the guard now
    refuses every such request whatever the patch contains.
    """
    session.brief = brief
    session.brief_meta = meta
    session.revision += 1
    session.updated_at = at
    complete = bool(brief.category and brief.target)
    session.state = state.require_transition(
        session.state, "brief_ready" if complete else "brief_filling"
    )
    if complete:
        session.needs_input = None
    return session


def finalize(session: Session, job_id: str, at: datetime) -> Session:
    """Lock the draft (INV-2) and hand the render to a job (INV-3).

    Two transitions in one call because the contract's 202 says so — "`state`가 `finalized`
    를 거쳐 `rendering`이 됩니다". They are separate edges in the state machine so that the
    "one render per session" guard has something to refuse a second time: after this,
    `rendering` has no edge back to `finalized`.
    """
    session.state = state.require_transition(session.state, "finalized")
    session.state = state.require_transition(session.state, "rendering")
    session.job_id = job_id
    session.updated_at = at
    return session


def complete(session: Session, at: datetime) -> Session:
    """The render finished. This is the end of the session's life."""
    session.state = state.require_transition(session.state, "completed")
    session.updated_at = at
    return session


def fail(session: Session, at: datetime) -> Session:
    """The render failed. Nothing leaves `failed`; the user starts a new session."""
    session.state = state.require_transition(session.state, "failed")
    session.updated_at = at
    return session

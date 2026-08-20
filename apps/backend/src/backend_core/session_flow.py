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
    check_draft_matches_output_type,
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
    # ⚠️ Checked before it is stored. The engine is a separate service, and a draft whose
    # shape contradicts the session's output type validates fine on its own — the union
    # accepts either member. Persisting one makes `Session.model_validate_json` fail on
    # every later read of that row, which is unrecoverable: the session cannot be read to be
    # fixed. Refusing here costs one failed generation instead.
    check_draft_matches_output_type(session.output_type, response.draft)
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

    Same pairing check as `apply_draft`, for the same reason: a mismatched draft written to
    the row makes every later read of that session fail.
    """
    check_draft_matches_output_type(session.output_type, draft)
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


@dataclass(frozen=True)
class RefillOutcome:
    """The result of asking the engine again after the user answered `needsInput`.

    ⚠️ `filled is None` means the inference **could not run** — the engine was unreachable or
    the photo it needs is gone. It does not mean "ran and found nothing"; that case arrives
    as a `filled` carrying its own `needsInput`. The contract splits the two on exactly this
    line (openapi.yaml `POST /v1/sessions`), and collapsing them would tell the user "we
    could not decide" about a request nobody ever made.
    """

    filled: BriefFillResponse | None


# The three brief fields `brief:fill` actually reads. A patch that touches none of them
# cannot change the inference, so asking again would spend a vendor call to receive the same
# answer — `artStyle` and `character` are not inputs to it.
REFILL_INPUTS = frozenset({"product_name", "selling_point", "note"})


def wants_refill(session: Session, patch: BriefPatch) -> bool:
    """Whether this patch is the user answering `needsInput`, and so deserves a retry.

    Two conditions, both necessary. The session has to be **waiting on the user** — a
    `needsInput` session is the only one the contract promises a retry for
    ("`needsInput`이 걸린 세션에서 `note`를 채우면 서버가 추론을 다시 시도합니다"). And the
    patch has to touch something the inference reads, or the retry is a paid call whose
    answer cannot differ.

    ⚠️ Deliberately **not** triggered on a `degraded` session. There the contract sends the
    user a different way out — they fill `category` and `target` themselves — and retrying
    an engine that was down a moment ago on every keystroke-sized patch turns an outage into
    a stampede.
    """
    if session.needs_input is None:
        return False
    return bool(patch.model_dump(exclude_unset=True).keys() & REFILL_INPUTS)


def merge_brief_patch(session: Session, patch: BriefPatch) -> tuple[Brief, BriefMeta]:
    """The merge half of `apply_brief_patch`, with no state change and no revision bump.

    Split out because the caller has to know **what the brief will say** before it can ask
    the engine to look at it again: the retry has to see the note the user just typed, not
    the one that already failed.

    ⚠️ Read with `exclude_unset`, which is the only correct way to read this family: an
    omitted key means "leave it alone" and `""` means "empty it", and they are opposite
    instructions. `exclude_none` would treat both as absent and quietly ignore every
    request to clear a field.

    Every field the user touches has its `filledBy` flipped to `user`, including one that
    was `inferred` a moment ago — 기획서 5.4 requires an auto-filled value to be visibly
    correctable, and a value the person just typed is no longer the model's guess.
    """
    changes = patch.model_dump(exclude_unset=True)
    # ⚠️ `model_validate` rather than `model_copy(update=...)`. `model_copy` does not
    # validate, and `model_dump` has already turned nested models into plain dicts — so a
    # patched `character` would sit on `Brief.character` as a `dict`, contradicting the
    # field's own annotation and drawing serializer warnings on the way out.
    brief = Brief.model_validate({**session.brief.model_dump(), **changes})
    check_brief_matches_output_type(session.output_type, brief)

    # `BriefMeta` carries exactly `Brief`'s keys — a conformance test enforces it — so every
    # changed field names a meta field, with no lookup needed to find out.
    meta = session.brief_meta.model_copy(update={field: _meta("user") for field in changes})
    return brief, meta


def apply_brief_patch(
    session: Session,
    patch: BriefPatch,
    at: datetime,
    refill: RefillOutcome | None = None,
) -> Session:
    """Merge the named brief fields, fold in a retry if one was run, and re-decide the state.

    `refill is None` means no retry was attempted, which is the ordinary patch. When one was
    attempted, its outcome decides two things the merge cannot:

    | refill | needsInput | messageMode |
    |---|---|---|
    | 없음 (재추론 안 함) | 그대로 | 그대로 |
    | 있음, `filled` 있음, 그 안에 `needsInput` 있음 | 새 `reason` 으로 교체 | `normal` |
    | 있음, `filled` 있음, `needsInput` 없음 | 지웁니다 | `normal` |
    | 있음, `filled` 없음 (돌지 못함) | 지웁니다 | `degraded` |

    ⚠️ **The last row clears `needsInput`, and that is the user's way out.** A session that
    could not run inference is a degraded session, and the contract already tells that user
    what to do: fill `category` and `target` themselves. Leaving `needsInput` on would keep
    the screen asking for a note that no longer leads anywhere.

    ⚠️ What this function still does **not** do is give up. A retry that comes back
    undecided leaves the session in `brief_filling`, exactly where it was. The contract
    promises a 422 `INSUFFICIENT_INPUT` there, but *when* to give up (first failure? third?)
    is 미결정_대장 B-11 and its 확정 근거 is 회의록 — so the ledger's own rule forbids
    picking a number here. The loop is narrower than it was, not closed.
    """
    brief, meta = merge_brief_patch(session, patch)
    if refill is not None:
        brief, meta = _fold_refill(brief, meta, refill.filled)
        session.message_mode = "normal" if refill.filled else "degraded"
        session.needs_input = refill.filled.needs_input if refill.filled else None
    return replace_brief(session, brief, meta, at)


def _fold_refill(
    brief: Brief, meta: BriefMeta, filled: BriefFillResponse | None
) -> tuple[Brief, BriefMeta]:
    """Take the inferred values, but **only where the user left a blank**.

    ⚠️ The user's own patch wins. If they typed a `category` in the very request that
    triggered this retry, overwriting it with the model's guess would undo a correction the
    person just made — 기획서 5.4 is that an auto-filled value stays visibly theirs to
    change, and this is the same rule read from the other side.
    """
    if filled is None:
        return brief, meta
    updates = {
        field: value
        for field, value in (("category", filled.category), ("target", filled.target))
        if value and not getattr(brief, field)
    }
    if not updates:
        return brief, meta
    return (
        brief.model_copy(update=updates),
        meta.model_copy(update={field: _meta("inferred") for field in updates}),
    )


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

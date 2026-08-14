"""The session state machine, as a table rather than as scattered `if` statements.

Source: 용어_사전.md 3.1절 (the diagram) and 도메인_모델.md 7절 (the invariants it enforces).
Three of the nine invariants are enforced here and nowhere else:

- **INV-2** — nothing changes after `finalized`. The table simply has no edge out of
  `finalized` except to `rendering`, so "patch after finalize" cannot be expressed.
- **INV-3** — one render per session. `rendering` is reachable only from `finalized`, and
  `finalized` only from `draft_ready`, so a second finalize finds no edge.
- **INV-7** — the brief is locked while a draft exists. `draft_generating` and everything
  after it have no edge back to `brief_ready` except the failure one (ADR-0012).

⚠️ Keep this a **table**, not a chain of conditionals. The invariants are stated as a
diagram in the documents, and a diagram compares to a table by eye. A chain of `if`s does
not, and the first thing that happens to one is a branch nobody notices is unreachable.

⚠️ FastAPI-free, like the rest of backend_core: the guard raises a domain error and the
API layer decides that it is a 409 (api/errors.py).
"""

from __future__ import annotations

from backend_core.models import SessionState

TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    "created": frozenset({"brief_filling"}),
    # 정보 부족으로 끝나는 간선이 여기 있습니다. 되돌아오는 간선은 없습니다.
    "brief_filling": frozenset({"brief_ready", "brief_filling", "failed"}),
    # brief patch 반복 (자기 자신으로), 그리고 시안 생성 요청.
    "brief_ready": frozenset({"brief_ready", "draft_generating"}),
    # 생성 실패로 brief_ready 에 되돌아오는 간선이 ADR-0012 입니다. 이것이 없으면
    # "브리프는 잠겼는데 시안은 없는" 세션이 빠져나갈 길 없이 남습니다.
    "draft_generating": frozenset({"draft_ready", "brief_ready"}),
    "draft_ready": frozenset({"draft_ready", "finalized"}),
    "finalized": frozenset({"rendering"}),
    "rendering": frozenset({"completed", "failed"}),
    # 끝입니다. completed 에서 렌더를 다시 걸 수 없는 것이 INV-3 이고,
    # failed 에서 되살릴 수 없는 것은 "새 세션을 만든다"는 결정입니다 (용어_사전 3.1절).
    "completed": frozenset(),
    "failed": frozenset(),
}
"""Allowed `current -> target` edges. Compare against the diagram in 용어_사전.md 3.1절."""


class StateConflictError(Exception):
    """The session is not in a state where this request means anything.

    Carries both states because the message a user sees has to say what the session *is*
    doing — "지금은 안 됩니다" with no further information is a support ticket.
    """

    def __init__(self, current: SessionState, target: SessionState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"cannot move a session from {current!r} to {target!r}")


def can_move(current: SessionState, target: SessionState) -> bool:
    """Whether the edge exists. Read-only; use it to answer "is this button live"."""
    return target in TRANSITIONS[current]


def require_transition(current: SessionState, target: SessionState) -> SessionState:
    """Take the edge, or refuse.

    Returns the target so call sites read as `session.state = require_transition(...)` —
    the check and the assignment in one expression, which is what stops the two from
    drifting apart when someone edits one of them.
    """
    if not can_move(current, target):
        raise StateConflictError(current, target)
    return target

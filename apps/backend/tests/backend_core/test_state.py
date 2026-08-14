"""The state machine against the diagram it comes from.

⚠️ Test names carry `INV-n` where the case is an invariant, as 도메인_모델.md 7.1절 requires
— it is what lets someone who breaks one find the rule from the failure line alone.

The first test is the important one: it compares the whole table to the edges written out
by hand from 용어_사전.md 3.1절. Testing individual transitions would leave an edge nobody
listed invisible, and an extra edge is exactly how an invariant stops being true.
"""

from __future__ import annotations

import pytest

from backend_core.state import TRANSITIONS, StateConflictError, can_move, require_transition

# Transcribed from the mermaid diagram in 용어_사전.md 3.1절, plus the two self-edges its
# prose describes ("brief patch 반복", "draft patch 반복").
DIAGRAM_EDGES = {
    ("created", "brief_filling"),
    ("brief_filling", "brief_ready"),
    ("brief_filling", "brief_filling"),
    ("brief_filling", "failed"),
    ("brief_ready", "brief_ready"),
    ("brief_ready", "draft_generating"),
    ("draft_generating", "draft_ready"),
    ("draft_generating", "brief_ready"),
    ("draft_ready", "draft_ready"),
    ("draft_ready", "finalized"),
    ("finalized", "rendering"),
    ("rendering", "completed"),
    ("rendering", "failed"),
}


def test_the_table_is_exactly_the_diagram() -> None:
    """No edge the diagram does not have, and none of the diagram's missing.

    An extra edge is not a cosmetic difference: every one of INV-2, INV-3 and INV-7 is true
    only because a particular edge is *absent*.
    """
    actual = {(source, target) for source, targets in TRANSITIONS.items() for target in targets}
    assert actual == DIAGRAM_EDGES


def test_every_state_has_an_entry() -> None:
    """A state missing from the table would raise `KeyError` instead of refusing, and a
    500 is not the contract's answer to "you cannot do that now"."""
    reachable = {target for targets in TRANSITIONS.values() for target in targets}
    assert reachable <= set(TRANSITIONS)


def test_inv_2_nothing_leaves_finalized_except_rendering() -> None:
    """INV-2: the draft cannot change after `finalized`.

    Enforced by absence — there is no edge from `finalized` back to `draft_ready`, so
    "patch after finalize" has no state to land in.
    """
    assert TRANSITIONS["finalized"] == frozenset({"rendering"})
    assert not can_move("finalized", "draft_ready")


def test_inv_3_a_session_can_only_render_once() -> None:
    """INV-3: one render per session, which is the cost defence.

    `rendering` is reachable only from `finalized`, and nothing returns to `finalized`. So a
    second finalize on a session that already rendered finds no edge, whether it is still
    rendering, `completed`, or `failed`.
    """
    assert {source for source, targets in TRANSITIONS.items() if "rendering" in targets} == {
        "finalized"
    }
    for spent in ("rendering", "completed", "failed"):
        assert not can_move(spent, "finalized"), spent


def test_inv_7_the_brief_locks_while_a_draft_exists() -> None:
    """INV-7: no route back to a brief-editing state once a draft exists.

    `draft_generating -> brief_ready` is the one exception and it is the failure edge
    (ADR-0012) — there is no draft yet in that case, so there is no evidence to protect.
    """
    assert not can_move("draft_ready", "brief_ready")
    assert can_move("draft_generating", "brief_ready")


def test_completed_and_failed_are_terminal() -> None:
    assert TRANSITIONS["completed"] == frozenset()
    assert TRANSITIONS["failed"] == frozenset()


def test_require_transition_returns_the_target_so_it_can_be_assigned() -> None:
    """The signature is the point: `session.state = require_transition(session.state, x)`
    puts the check and the assignment in one expression, so neither can be edited without
    the other."""
    assert require_transition("created", "brief_filling") == "brief_filling"


def test_a_refused_transition_names_both_states() -> None:
    """The message reaches a user as a 409 body. "지금은 안 됩니다" with no further detail is
    a support ticket."""
    with pytest.raises(StateConflictError) as caught:
        require_transition("completed", "rendering")

    assert caught.value.current == "completed"
    assert caught.value.target == "rendering"

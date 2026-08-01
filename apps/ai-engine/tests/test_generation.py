"""Generation orchestration: retrieve -> generate -> verify -> answer or refuse."""

import pytest
from conftest import ANSWERABLE_QUESTION, UNANSWERABLE_QUESTION

from ai_engine.generation import (
    GenerationFailedError,
    StubGenerator,
    generate_answer,
)
from ai_engine.models import GenerateRequest
from ai_engine.retrieval import FixtureRetriever


class BrokenGenerator:
    """A model client that is down — not a refusal, an outage."""

    def complete(self, prompt: str) -> str:
        raise RuntimeError("model client exploded")


class InventingGenerator:
    """Returns fluent text with no basis in the evidence — what the guardrail exists for."""

    def complete(self, prompt: str) -> str:
        return "환불 수수료는 5000원이며 매장에서 현금으로 돌려받습니다."


def test_grounded_question_is_answered(retriever: FixtureRetriever) -> None:
    response = generate_answer(
        GenerateRequest(question=ANSWERABLE_QUESTION), retriever, StubGenerator()
    )
    assert response.answer
    assert response.sources
    assert response.refusal_reason is None
    assert response.guardrail_applied is True


def test_no_evidence_refuses_without_inventing(retriever: FixtureRetriever) -> None:
    response = generate_answer(
        GenerateRequest(question=UNANSWERABLE_QUESTION), retriever, StubGenerator()
    )
    assert response.answer is None
    assert response.refusal_reason == "no_evidence"


def test_hallucination_is_refused(retriever: FixtureRetriever) -> None:
    """Sources are still returned so the caller can show what *was* found."""
    response = generate_answer(
        GenerateRequest(question=ANSWERABLE_QUESTION), retriever, InventingGenerator()
    )
    assert response.answer is None
    assert response.refusal_reason == "guardrail"
    assert response.sources


def test_control_run_reports_that_it_was_unverified(retriever: FixtureRetriever) -> None:
    """Guardrail off is the eval control condition — the response must say so."""
    response = generate_answer(
        GenerateRequest(question=ANSWERABLE_QUESTION),
        retriever,
        InventingGenerator(),
        guardrail_enabled=False,
    )
    assert response.answer is not None
    assert response.guardrail_applied is False


def test_model_outage_raises_rather_than_refusing(retriever: FixtureRetriever) -> None:
    """An outage is a 503; a refusal is a 200. Collapsing them hides real failures."""
    with pytest.raises(GenerationFailedError):
        generate_answer(GenerateRequest(question=ANSWERABLE_QUESTION), retriever, BrokenGenerator())

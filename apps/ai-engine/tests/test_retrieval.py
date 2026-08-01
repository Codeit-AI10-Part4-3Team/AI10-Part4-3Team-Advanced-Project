"""Retrieval behaviour.

Convention: tests/ mirrors src/ (src/ai_engine/retrieval.py -> tests/test_retrieval.py).
"""

from conftest import ANSWERABLE_QUESTION, UNANSWERABLE_QUESTION

from ai_engine.retrieval import FixtureRetriever


def test_corpus_loads(retriever: FixtureRetriever) -> None:
    assert retriever.passages, "번들 코퍼스가 비어 있으면 모든 응답이 조용히 거절로 떨어집니다"


def test_relevant_question_retrieves_something(retriever: FixtureRetriever) -> None:
    hits = retriever.search(ANSWERABLE_QUESTION, top_k=3)
    assert hits
    assert "환불" in hits[0].text


def test_unrelated_question_retrieves_nothing(retriever: FixtureRetriever) -> None:
    """The overlap floor is what stops the engine answering from unrelated evidence."""
    assert retriever.search(UNANSWERABLE_QUESTION, top_k=3) == []


def test_ordering_is_stable(retriever: FixtureRetriever) -> None:
    """Scoring ties break on id so repeated runs — and therefore metrics — are reproducible."""
    first = [p.id for p in retriever.search(ANSWERABLE_QUESTION, top_k=3)]
    second = [p.id for p in retriever.search(ANSWERABLE_QUESTION, top_k=3)]
    assert first == second

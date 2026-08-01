"""Domain behaviour, exercised without FastAPI.

That this file imports nothing from `api` is the point: if it ever needs to, the
dependency direction has been inverted and the domain is no longer testable on its own.
"""

from conftest import GROUNDED_TEXT, FakeAiEngine

from backend_core.pipeline import FALLBACK_TEXT, answer_question


def test_grounded_answer_is_passed_through() -> None:
    answer = answer_question("어디로 가야 하나요?", "ko", FakeAiEngine())
    assert answer.message_mode == "grounded"
    assert answer.text == GROUNDED_TEXT
    assert answer.sources


def test_refusal_falls_back() -> None:
    """A refusal is not an error — it means the engine declined to invent an answer."""
    answer = answer_question("근거 없는 질문", "ko", FakeAiEngine(refuses=True))
    assert answer.message_mode == "official_fallback"
    assert answer.text == FALLBACK_TEXT
    assert answer.sources == []


def test_outage_falls_back_to_the_same_place() -> None:
    """Refusal and outage collapse to one response so no client has to tell them apart."""
    answer = answer_question("어디로 가야 하나요?", "ko", FakeAiEngine(available=False))
    assert answer.message_mode == "official_fallback"
    assert answer.text == FALLBACK_TEXT

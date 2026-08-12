"""The one flow that threads the whole system — the walking skeleton.

    question -> ai-engine 호출 -> (근거 있으면) grounded / (없거나 장애면) official_fallback

Every branch ends in a usable answer. That is the point: the degraded path is a designed
behaviour, not an error page, and it is visible to the caller as `messageMode` rather
than being disguised as a live result.

⚠️ Keep this module FastAPI-free. It is imported by tests and by any offline harness.
"""

from __future__ import annotations

from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError
from backend_core.models.legacy_qa import Answer

# Pre-approved text used whenever we cannot ground an answer. Replace with your domain's
# officially approved copy; keep it short and actionable.
FALLBACK_TEXT = "지금은 정확한 답변을 드릴 수 없습니다. 공식 안내 채널을 확인해 주세요."


def answer_question(question: str, locale: str, ai: AiEngineClient) -> Answer:
    """Ask the engine, and never return empty-handed.

    Both failure modes collapse to the same fallback on purpose — from the caller's side
    "the engine refused" and "the engine was down" are the same situation, and splitting
    them into different responses only pushes that decision onto every client.
    """
    try:
        generated = ai.generate(question, locale)
    except AiEngineUnavailableError:
        generated = None

    if generated is None:
        return Answer(text=FALLBACK_TEXT, message_mode="official_fallback", sources=[])
    return generated

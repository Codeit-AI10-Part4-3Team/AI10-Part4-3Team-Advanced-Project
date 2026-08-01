"""Shared fixtures for ai-engine tests.

Everything here runs offline: no model API, no embedding API, no network. External calls
in tests cost money and make CI non-deterministic (AGENTS.md).
"""

import pytest

from ai_engine.retrieval import FixtureRetriever

# A question the bundled dummy corpus can actually answer. Keep it in sync with
# src/ai_engine/fixtures/corpus.jsonl — if the corpus changes and this does not, the
# tests start asserting on the refusal path without anyone noticing.
ANSWERABLE_QUESTION = "환불은 어떻게 하나요?"
UNANSWERABLE_QUESTION = "내일 주식 시장 전망을 알려주세요"


@pytest.fixture
def retriever() -> FixtureRetriever:
    return FixtureRetriever.from_jsonl()

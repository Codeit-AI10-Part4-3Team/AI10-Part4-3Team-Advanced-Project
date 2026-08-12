"""Shared fixtures.

Every test runs fully offline. The AI engine is replaced with a fake through FastAPI's
dependency overrides — external calls in tests cost money, are rate-limited and make CI
non-deterministic (AGENTS.md).

⚠️ The fake mimics the engine's *contract*, including both failure modes: a refusal
(`generate` returns `None`) and an outage (raises). It does not bypass the guardrail —
guardrail behaviour is tested in apps/ai-engine, where it lives.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.ai_client import AiEngineUnavailableError
from backend_core.models.legacy_qa import Answer, Source

GROUNDED_TEXT = "안내문 3조에 따라 먼저 담당 창구에 연락하세요."

# tests/ -> apps/backend/ -> apps/ -> repo root
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.yaml"


@pytest.fixture(scope="session")
def contract_schemas() -> dict[str, Any]:
    """`components.schemas` from the contract, for the conformance tests.

    Read straight from the spec rather than copied into the test: a copy drifts with the
    models it is supposed to police, which is the failure this fixture exists to prevent.

    Skips rather than fails when the file is missing — this app is installable on its own,
    and a missing monorepo sibling is an environment fact, not a broken model.
    """
    if not CONTRACT_PATH.exists():
        pytest.skip(f"contract not found at {CONTRACT_PATH}")
    spec: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    schemas: dict[str, Any] = spec["components"]["schemas"]
    return schemas


class FakeAiEngine:
    """Contract-shaped stand-in.

    `available=False` simulates the outage branch (raise); `refuses=True` simulates the
    honest-refusal branch (`answer: null`). Both must end at the same place — the
    backend's `official_fallback` — which is what the pipeline tests check.
    """

    def __init__(self, available: bool = True, refuses: bool = False) -> None:
        self.available = available
        self.refuses = refuses
        self.seen: list[str] = []

    def generate(self, question: str, locale: str) -> Answer | None:
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        self.seen.append(question)
        if self.refuses:
            return None
        return Answer(
            text=GROUNDED_TEXT,
            message_mode="grounded",
            sources=[Source(title="[더미] 공식 안내문", quote="담당 창구에 연락합니다.")],
        )


@pytest.fixture
def ai() -> FakeAiEngine:
    return FakeAiEngine()


@pytest.fixture
def client(ai: FakeAiEngine) -> Iterator[TestClient]:
    """App wired to per-test collaborators.

    The real providers are `lru_cache`d singletons, so without these overrides state would
    leak between tests and the first test to run would poison the rest.
    """
    app.dependency_overrides[deps.ai_client] = lambda: ai
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

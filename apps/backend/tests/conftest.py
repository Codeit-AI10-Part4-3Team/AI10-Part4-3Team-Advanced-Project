"""Shared fixtures.

Every test runs fully offline. The AI engine is replaced with a fake through FastAPI's
dependency overrides — external calls in tests cost money, are rate-limited and make CI
non-deterministic (AGENTS.md).

⚠️ The fake mimics the engine's *contract*, including both failure modes: a refusal
(`generate` returns `None`) and an outage (raises). It does not bypass the guardrail —
guardrail behaviour is tested in apps/ai-engine, where it lives.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.ai_client import AiEngineUnavailableError
from backend_core.models import Answer, Source

GROUNDED_TEXT = "안내문 3조에 따라 먼저 담당 창구에 연락하세요."


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cut every test off from the machine's own configuration.

    Startup now creates the schema and seeds the fixed accounts (api.main.lifespan), so
    without this two things happen: the suite writes a real database into the working
    directory, and a developer who has infra/.env exported in their shell runs the tests
    against their own accounts. The second is worse — it passes locally and fails in CI.

    `deps.settings` is an `lru_cache`d singleton read outside the request cycle, so
    `dependency_overrides` cannot reach it; clearing the cache is what makes the patched
    environment take effect.
    """
    for name in [name for name in os.environ if name.startswith("ADGEN_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "test.sqlite"))

    deps.settings.cache_clear()
    yield
    deps.settings.cache_clear()


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

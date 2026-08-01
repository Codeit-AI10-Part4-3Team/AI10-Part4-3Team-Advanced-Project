"""Dependency wiring.

Every collaborator a router uses is resolved through a `Depends(...)` provider so tests
can substitute it via `app.dependency_overrides` — including the AI engine, which must
never be called for real from a test (external calls cost money and make CI
non-deterministic).

Each provider is the named seam where a stub gets replaced by the real thing. Replace a
stub *at* its seam, not around it.
"""

from functools import lru_cache

from backend_core.ai_client import AiEngineClient, HttpAiEngineClient
from backend_core.config import Settings, get_settings


@lru_cache(maxsize=1)
def settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def ai_client() -> AiEngineClient:
    return HttpAiEngineClient(settings().ai_engine_url, settings().ai_engine_timeout_s)

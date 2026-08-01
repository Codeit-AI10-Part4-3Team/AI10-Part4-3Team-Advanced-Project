"""Runtime settings.

Values come from the environment (infra/.env, never committed). Defaults are the local
docker-compose topology so a fresh clone runs without configuration — a skeleton that
needs a filled-in .env before it moves is not a walking skeleton.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`ADGEN_` prefix keeps our variables distinguishable from everything else on the host."""

    model_config = SettingsConfigDict(env_prefix="ADGEN_", extra="ignore")

    # Service name of the AI engine in docker-compose; localhost when run bare.
    ai_engine_url: str = "http://localhost:8100"

    # A generation call that overruns this has not been "slow", it has missed the request.
    # We cut it and fall back rather than letting the caller wait.
    ai_engine_timeout_s: float = 8.0


def get_settings() -> Settings:
    """Read settings. Callers cache — see api.deps, which holds the single instance."""
    return Settings()

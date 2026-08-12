"""Runtime settings.

Values come from the environment (infra/.env, never committed). Defaults are the local
docker-compose topology so a fresh clone runs without configuration — a skeleton that
needs a filled-in .env before it moves is not a walking skeleton.

⚠️ The auth fields below have empty defaults, and that emptiness is *not* a usable value.
A committed default signing key is a published signing key (ADR-0013), and the fixed
accounts only exist in infra/.env anyway (ADR-0008). The check that rejects an empty
secret lives in the auth wiring, not here: this class is also read by /health and /v1/ask,
which must keep working on a fresh clone with no .env at all.
"""

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The cookie name is contract surface (openapi.yaml securitySchemes), not an operator
# knob: renaming it silently logs every client out. Kept as a constant so it cannot drift
# per-environment. The *lifetime* is configurable — see Settings.session_max_age_s.
SESSION_COOKIE_NAME = "session_token"


class SeedAccount(BaseModel):
    """One pre-made account. Signup is 501, so accounts only ever arrive this way.

    ⚠️ `password_hash` is a hash, never a plaintext password. Nothing in this codebase
    accepts a plaintext password from configuration — that is how they end up in logs and
    in shell history.
    """

    login_id: str = Field(min_length=1, max_length=64)
    password_hash: str = Field(min_length=1)

    @field_validator("password_hash")
    @classmethod
    def _must_look_like_a_hash(cls, value: str) -> str:
        """Reject a hash that docker-compose ate on the way in.

        Compose reads `$` inside a .env value as a variable reference, so an un-escaped
        argon2 hash arrives as `=19=65536,t=3,p=4` — still a non-empty string, so nothing
        downstream notices until a login silently fails. infra/README.md documents the
        `$$` escaping; this check is here because a rule people have to remember is not a
        defence. Deliberately shape-only: verifying the hash for real is argon2's job.
        """
        if not value.startswith("$argon2"):
            raise ValueError(
                "password hash is not an argon2 hash. If it came through docker-compose, "
                "`$` must be written as `$$` in infra/.env "
                "(see infra/README.md, 환경변수 값에 `$`가 들어갈 때)"
            )
        return value


class Settings(BaseSettings):
    """`ADGEN_` prefix keeps our variables distinguishable from everything else on the host."""

    model_config = SettingsConfigDict(env_prefix="ADGEN_", extra="ignore")

    # Service name of the AI engine in docker-compose; localhost when run bare.
    ai_engine_url: str = "http://localhost:8100"

    # A generation call that overruns this has not been "slow", it has missed the request.
    # We cut it and fall back rather than letting the caller wait.
    ai_engine_timeout_s: float = 8.0

    # ---- auth (ADR-0008, ADR-0013) -----------------------------------------------------

    # Signs the session token. No default: see the module docstring.
    session_secret: str = ""

    # 24h, no refresh (세션_보관_정책.md 1.4절). Configurable because the number is a
    # guess about the theft window, and a guess in code needs a deploy to revise.
    session_max_age_s: int = 86400

    # JSON list, e.g. [{"login_id": "...", "password_hash": "$argon2id$..."}].
    # snake_case, not the contract's camelCase: this is operator configuration, not wire
    # format. Nothing here is ever serialised to a client.
    # Two accounts are the minimum that can prove INV-9 — with one, "someone else's
    # session" does not exist and the 404 path is never taken (ADR-0008). Not enforced
    # here: individual devs may seed extra accounts locally (구현_범위.md 1절).
    accounts: list[SeedAccount] = Field(default_factory=list)


def get_settings() -> Settings:
    """Read settings. Callers cache — see api.deps, which holds the single instance."""
    return Settings()

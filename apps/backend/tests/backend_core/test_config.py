"""Settings that guard against a misconfigured environment.

The interesting case is not "does pydantic parse JSON" but "does a value that
docker-compose corrupted on the way in get caught". See infra/README.md, section
"환경변수 값에 `$`가 들어갈 때".
"""

import pytest
from pydantic import ValidationError

from backend_core.config import SESSION_COOKIE_NAME, SeedAccount, Settings

# A real argon2id hash shape. The `$` separators are what compose eats.
ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaGVkdmFsdWU"

# What arrives when infra/.env forgot to write `$` as `$$`: the `$argon2id`,
# `$c29tZXNhbHQ` and `$aGFzaGVk...` segments are read as variable references and
# substituted with empty strings. Still a non-empty string, which is why it needs
# catching here rather than at login time.
COMPOSE_MANGLED = "=19=65536,t=3,p=4"

# Named rather than inlined: ruff (S106) flags a string literal passed to a
# password-shaped argument, and it is right to — this value only exists to be rejected.
PLAINTEXT_NOT_A_HASH = "hunter2"


def test_seed_account_accepts_an_argon2_hash() -> None:
    account = SeedAccount(login_id="demo1", password_hash=ARGON2_HASH)
    assert account.password_hash == ARGON2_HASH


def test_seed_account_rejects_a_compose_mangled_hash() -> None:
    """A silently corrupted hash must fail at startup, not at the first login."""
    with pytest.raises(ValidationError) as caught:
        SeedAccount(login_id="demo1", password_hash=COMPOSE_MANGLED)

    # The message has to name the fix; whoever hits this is looking at a container that
    # will not start and has no other clue.
    assert "$$" in str(caught.value)


def test_seed_account_rejects_a_plaintext_password() -> None:
    """Configuration takes hashes only. A plaintext password here would be stored,
    logged and shell-historied, and it fails the same shape check."""
    with pytest.raises(ValidationError):
        SeedAccount(login_id="demo1", password_hash=PLAINTEXT_NOT_A_HASH)


def test_accounts_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{ARGON2_HASH}"}}]',
    )
    assert Settings().accounts[0].login_id == "demo1"


def test_auth_defaults_are_empty_not_guessable(monkeypatch: pytest.MonkeyPatch) -> None:
    """No default signing key and no default accounts.

    A committed default signing key is a published one (ADR-0013). The emptiness is
    rejected by the auth wiring, not here — /health and /v1/ask must keep working on a
    fresh clone with no .env at all.
    """
    monkeypatch.delenv("ADGEN_SESSION_SECRET", raising=False)
    monkeypatch.delenv("ADGEN_ACCOUNTS", raising=False)

    settings = Settings()

    assert settings.session_secret == ""
    assert settings.accounts == []
    # 24h, no refresh (세션_보관_정책.md 1.4절).
    assert settings.session_max_age_s == 86400


def test_cookie_name_matches_the_contract() -> None:
    """openapi.yaml's securitySchemes names this cookie. Renaming it logs everyone out,
    so it is a constant rather than an operator knob."""
    assert SESSION_COOKIE_NAME == "session_token"

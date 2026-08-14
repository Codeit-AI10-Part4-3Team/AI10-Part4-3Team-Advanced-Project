"""Settings that guard against a misconfigured environment.

The interesting case is not "does pydantic parse JSON" but "does a value that
docker-compose corrupted on the way in get caught". See infra/README.md, section
"환경변수 값에 `$`가 들어갈 때".
"""

import pytest
from pydantic import ValidationError

from backend_core.config import SeedAccount, Settings

# A real argon2id hash shape. The `$` separators are what compose eats.
ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaGVkdmFsdWU"

# What arrives when infra/.env forgot to write `$` as `$$`: the `$argon2id`,
# `$c29tZXNhbHQ` and `$aGFzaGVk...` segments are read as variable references and
# substituted with empty strings. Still a non-empty string, which is why it needs
# catching here rather than at login time.
COMPOSE_MANGLED = "=19=65536,t=3,p=4"


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


@pytest.mark.parametrize(
    "truncated",
    ["$argon2", "$argon2id$v=19", "$argon2id$v=19$m=65536,t=3,p=4"],
    ids=["prefix only", "no parameters", "no salt or digest"],
)
def test_seed_account_rejects_a_hash_that_only_starts_right(truncated: str) -> None:
    """⚠️ Regression guard. A prefix check (`startswith("$argon2")`) let all three of these
    through, and argon2 then rejected them at *login* — one of them with `InvalidHashError`,
    which is a `ValueError` rather than an `Argon2Error` and so escaped the handler in
    `accounts.authenticate` and reached the client as a 500 (2026-08-13 실측).

    The parse belongs at startup: a broken configuration value should stop the container,
    not surface later as an unexplained error on a login screen.
    """
    with pytest.raises(ValidationError):
        SeedAccount(login_id="demo1", password_hash=truncated)


def test_accounts_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{ARGON2_HASH}"}}]',
    )
    assert Settings().accounts[0].login_id == "demo1"


@pytest.mark.parametrize("blank", ["", "   ", "\n"], ids=["empty", "spaces", "newline"])
def test_a_blank_accounts_variable_means_no_accounts(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ Regression guard, and the distinction it draws is the whole point: **set-but-empty
    is not the same as unset.**

    `docker-compose.yml` writes `ADGEN_ACCOUNTS: ${ADGEN_ACCOUNTS:-}`, so a stack brought up
    without infra/.env sets the variable to an empty string. pydantic-settings then tried to
    JSON-decode `""` and raised `SettingsError` — not a validation error the app could
    answer, but a failure during construction of `Settings`, which killed the process at
    startup and took `/health` with it (2026-08-14 실측, CI 종단 관통 테스트).

    A stack with no accounts is a supported state: nobody can log in, everything else works.
    """
    monkeypatch.setenv("ADGEN_ACCOUNTS", blank)
    assert Settings().accounts == []


def test_malformed_accounts_json_names_the_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Genuinely broken JSON still has to fail — loudly, and with the shape in the message.

    Whoever hits this is looking at a container that will not start, and the variable is one
    long line in a file they cannot see the parser's opinion of.
    """
    monkeypatch.setenv("ADGEN_ACCOUNTS", "demo1:demo1-password")

    with pytest.raises(ValidationError) as caught:
        Settings()

    assert "login_id" in str(caught.value)


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

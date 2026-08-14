"""What has to be true before the first request arrives.

Deployment is `git pull` + `docker compose up` with no migration step (ADR-0011), so
startup is the only place the schema and the fixed accounts can come from. A missing table
would surface as a 500 on the first login, which reads as "the app is broken" rather than
"the app never set itself up".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.accounts import authenticate, find_by_login_id
from backend_core.storage import connect
from backend_core.tokens import SigningKeyMissingError

PLAINTEXT_DEMO1 = "correct-horse-battery-staple"
PLAINTEXT_DEMO2 = "not-the-one"


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A deployment-shaped environment: two seeded accounts and a signing key.

    Two rather than one because that is the documented minimum (ADR-0008) — with one
    account there is no "someone else" and INV-9's 404 path is never taken.
    """
    hasher = PasswordHasher()
    db_path = tmp_path / "startup.sqlite"

    monkeypatch.setenv("ADGEN_DB_PATH", str(db_path))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        json.dumps(
            [
                {"login_id": "demo1", "password_hash": hasher.hash(PLAINTEXT_DEMO1)},
                {"login_id": "demo2", "password_hash": hasher.hash(PLAINTEXT_DEMO2)},
            ]
        ),
    )
    deps.settings.cache_clear()
    return db_path


def test_startup_creates_the_schema_and_seeds_the_accounts(configured: Path) -> None:
    with TestClient(app):
        pass

    with connect(configured) as connection:
        assert authenticate(connection, "demo1", PLAINTEXT_DEMO1) is not None
        assert authenticate(connection, "demo2", PLAINTEXT_DEMO2) is not None


def test_restarting_does_not_re_issue_user_ids(configured: Path) -> None:
    """INV-9 again, this time through the real startup path rather than a direct `seed`
    call. Sessions reference `user_id`; if a restart moved it, every session that user owns
    would 404 after a deploy and reach the user as "my work disappeared"."""
    with TestClient(app):
        pass
    with connect(configured) as connection:
        before = find_by_login_id(connection, "demo1")

    with TestClient(app):
        pass
    with connect(configured) as connection:
        after = find_by_login_id(connection, "demo1")

    assert before is not None and after is not None
    assert before.user_id == after.user_id


def test_configured_accounts_without_a_signing_key_refuse_to_start(
    configured: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0013: no default for the signing key, and the absence stops the process. If it
    only stopped the first login, a deployment would look healthy right up until someone
    tried to use it."""
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "")
    deps.settings.cache_clear()

    with pytest.raises(SigningKeyMissingError), TestClient(app):
        pass  # pragma: no cover - the context manager raises on entry


def test_a_half_configured_server_answers_401_not_500(client: TestClient) -> None:
    """A cookie arriving where no signing key is configured.

    The startup check only fires when accounts are configured, so this state is reachable:
    a bare clone that someone points a browser at. Before the fix `tokens.verify` raised on
    the empty key and the client got a 500 with a stack trace. No key means no token can be
    valid, so 401 is the honest answer — and it must never become "verify with an empty
    key", which would accept whatever an attacker signs with the same emptiness.
    """
    for method, path in [("get", "/v1/me"), ("post", "/v1/auth/logout")]:
        response = client.request(method, path, headers={"Cookie": "session_token=anything"})

        assert response.status_code == 401, path
        assert response.json()["code"] == "UNAUTHORIZED"


def test_accounts_left_on_the_volume_stop_a_keyless_restart(
    configured: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ Regression guard. **Accounts live in the database, not in the environment**, and
    the startup check has to ask the database.

    The sequence, from the PR #84 review (신호정):

    1. a configured run seeds `demo1` into the file and logging in returns 200;
    2. the stack restarts against the **same volume** with `ADGEN_ACCOUNTS` and
       `ADGEN_SESSION_SECRET` both empty. `seed([])` deletes nothing, so `demo1` is still
       there — but the old check looked at `settings.accounts`, saw an empty list, and
       skipped `require_secret`. `/health` answered 200;
    3. logging in with the **correct** password then reached `tokens.issue`, which raised on
       the empty key — a 500.

    That inverts the rule this app is built on (ADR-0013): a missing key stops the process,
    it does not stop the first login. Startup is where a misconfiguration is cheap to see;
    a 500 on a correct password is where it is most expensive.
    """
    with TestClient(app):
        pass
    with connect(configured) as connection:
        assert find_by_login_id(connection, "demo1") is not None, "the fixture must seed first"

    monkeypatch.setenv("ADGEN_ACCOUNTS", "")
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "")
    deps.settings.cache_clear()

    with pytest.raises(SigningKeyMissingError), TestClient(app):
        pass  # pragma: no cover - the context manager raises on entry


def test_a_bare_clone_still_starts(client: TestClient) -> None:
    """No .env at all: no accounts, no signing key. The app must still come up and serve
    /health, because a skeleton that needs configuration before it moves is not a walking
    skeleton (backend_core/config.py). `client` comes from conftest, which strips every
    ADGEN_ variable — that is the bare-clone condition."""
    assert client.get("/health").status_code == 200


def test_an_unconfigured_compose_stack_still_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same as above, except the variables are **empty rather than absent**.

    ⚠️ These are two different conditions and only the first one was covered. Compose writes
    `ADGEN_ACCOUNTS: ${ADGEN_ACCOUNTS:-}`, which *sets* the variable to an empty string, so
    `docker compose up` with no infra/.env lands here and not in the test above. Before the
    fix pydantic-settings tried to JSON-decode `""` and the process died at startup —
    every route gone, `/health` included, so the container never became healthy
    (2026-08-14, CI 종단 관통 테스트).
    """
    monkeypatch.setenv("ADGEN_ACCOUNTS", "")
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "")
    deps.settings.cache_clear()

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

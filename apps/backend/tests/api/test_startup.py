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


def test_a_bare_clone_still_starts(client: TestClient) -> None:
    """No .env at all: no accounts, no signing key. The app must still come up and serve
    /health, because a skeleton that needs configuration before it moves is not a walking
    skeleton (backend_core/config.py). `client` comes from conftest, which strips every
    ADGEN_ variable — that is the bare-clone condition."""
    assert client.get("/health").status_code == 200

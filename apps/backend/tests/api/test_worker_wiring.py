"""The background worker, wired into a running app.

⚠️ `tests/backend_core/test_render.py` covers what a render *does*; this file covers how the
worker gets its collaborators. That is a separate question and it had a real answer wrong:
the worker called `deps.ai_client()` directly, `app.dependency_overrides` does not reach a
direct call, and so a test suite went out to **localhost:8100** over the network while a job
sat `running` for the render timeout (2026-08-14 실측).

Test suites must never make external calls (AGENTS.md), and a job that hangs on one is not a
slow test — it is a test asserting against a state nothing will ever leave.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher
from conftest import VALID_PNG, FakeAiEngine
from fastapi.testclient import TestClient

from api import deps
from api.main import app

PASSWORD = "correct-horse-battery-staple"  # noqa: S105


@pytest.fixture
def engine() -> FakeAiEngine:
    return FakeAiEngine()


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "worker.sqlite"))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    # The one place the worker is deliberately on. conftest turns it off everywhere else.
    monkeypatch.setenv("ADGEN_WORKER_ENABLED", "true")
    monkeypatch.setenv("ADGEN_WORKER_POLL_INTERVAL_S", "0.05")
    deps.settings.cache_clear()


def _finalize(client: TestClient) -> str:
    created = client.post(
        "/v1/sessions",
        data={
            "outputType": "single_ad",
            "productName": "테스트 제품",
            "sellingPoint": "수분감이 오래 갑니다",
            "note": "",
        },
        files={"productImage": ("photo.png", VALID_PNG, "image/png")},
    )
    session_id = created.json()["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")
    job_id: str = client.post(f"/v1/sessions/{session_id}/finalize").json()["jobId"]
    return job_id


def _poll_until_done(client: TestClient, job_id: str, seconds: float = 5.0) -> dict[str, Any]:
    """Poll the way a client is told to. Fails loudly rather than hanging."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        body: dict[str, Any] = client.get(f"/v1/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    pytest.fail(f"job {job_id} never finished; last status was {body['status']}")


def test_the_worker_uses_the_engine_the_test_substituted(
    configured: None, engine: FakeAiEngine
) -> None:
    """⚠️ The regression guard for the defect this file exists for.

    `renders_requested` on the **fake** is the proof: if the worker had resolved its own
    client, the fake would be untouched and the job would be stuck against a real socket.
    """
    app.dependency_overrides[deps.ai_client] = lambda: engine
    with TestClient(app, base_url="https://testserver") as client:
        client.post("/v1/auth/login", json={"loginId": "demo1", "password": PASSWORD})
        job_id = _finalize(client)
        finished = _poll_until_done(client, job_id)
    app.dependency_overrides.clear()

    assert finished["status"] == "done"
    assert len(engine.renders_requested) == 1


def test_polling_reaches_done_the_way_a_client_would(
    configured: None, engine: FakeAiEngine
) -> None:
    """S6's completion condition, through HTTP only: `finalize` then poll until `done`."""
    app.dependency_overrides[deps.ai_client] = lambda: engine
    with TestClient(app, base_url="https://testserver") as client:
        client.post("/v1/auth/login", json={"loginId": "demo1", "password": PASSWORD})
        job_id = _finalize(client)
        finished = _poll_until_done(client, job_id)

        assert finished["result"]["imageUrl"]
        # `Retry-After` is only sent while there is a next poll to make.
        assert "Retry-After" not in client.get(f"/v1/jobs/{job_id}").headers
    app.dependency_overrides.clear()


def test_the_worker_is_off_unless_a_test_asks_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: FakeAiEngine
) -> None:
    """The default in the suite, and why the other tests can assert on `queued` at all.

    ⚠️ Without this, every job-state assertion in the suite races a background poll and
    passes or fails on machine speed.
    """
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "off.sqlite"))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    deps.settings.cache_clear()

    app.dependency_overrides[deps.ai_client] = lambda: engine
    with TestClient(app, base_url="https://testserver") as client:
        client.post("/v1/auth/login", json={"loginId": "demo1", "password": PASSWORD})
        job_id = _finalize(client)
        time.sleep(0.3)
        status = client.get(f"/v1/jobs/{job_id}").json()["status"]
    app.dependency_overrides.clear()

    assert status == "queued"
    assert engine.renders_requested == []

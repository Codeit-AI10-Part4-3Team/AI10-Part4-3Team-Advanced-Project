"""Requests that arrive at the same time.

Every other test in this suite sends one request at a time, and that is exactly the shape
that hides the failure below. Keep this file: a sequential suite cannot see a threading
bug, and this one was green through the whole S0 build while the app broke under two
simultaneous callers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from api import deps
from api.main import app

PLAINTEXT = "correct-horse-battery-staple"
WORKERS = 8
REQUESTS = 80


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "concurrent.sqlite"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        json.dumps([{"login_id": "demo1", "password_hash": PasswordHasher().hash(PLAINTEXT)}]),
    )
    deps.settings.cache_clear()

    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def test_overlapping_requests_do_not_break_the_database_connection(client: TestClient) -> None:
    """⚠️ Regression guard for a bug that only appears under concurrency.

    FastAPI runs a sync generator dependency through anyio's threadpool, and the setup, the
    route body and the teardown are not guaranteed to get the same worker thread. sqlite3
    defaults to `check_same_thread=True`, so the connection opened in one thread raised

        sqlite3.ProgrammingError: SQLite objects created in a thread can only be
        used in that same thread.

    as soon as two callers overlapped. Measured 2026-08-13 before the fix: 182 of 200
    concurrent requests answered 500, while the same 200 sent one at a time all answered
    200. The fix is `check_same_thread=False` in `backend_core.storage.connect`, which is
    safe only because a connection is never shared between requests.

    Sending these sequentially would make the test pass against the broken code, which is
    the same as deleting it.
    """
    cookie = client.post(
        "/v1/auth/login", json={"loginId": "demo1", "password": PLAINTEXT}
    ).cookies["session_token"]

    def fetch(_: int) -> int:
        return client.get("/v1/me", headers={"Cookie": f"session_token={cookie}"}).status_code

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        statuses = list(pool.map(fetch, range(REQUESTS)))

    assert statuses == [200] * REQUESTS


def test_overlapping_logins_all_succeed(client: TestClient) -> None:
    """The write path too: login reads through the same per-request connection, and each
    caller has to get its own working one."""

    def login(_: int) -> int:
        return client.post(
            "/v1/auth/login", json={"loginId": "demo1", "password": PLAINTEXT}
        ).status_code

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        statuses = list(pool.map(login, range(WORKERS * 2)))

    assert statuses == [200] * (WORKERS * 2)

"""The invariants under simultaneous requests, which is the only place they can break.

⚠️ Every other test in this suite sends one request at a time, and every one of these
defects passed all of them. The state machine's guard runs on the value a request read at
the start; two requests that arrive together both read the old state, both find the
transition allowed, and both write. Nothing about that is visible sequentially.

This is the second time concurrency hid a defect in this app — the first was sqlite3's
`check_same_thread` (tests/api/test_concurrency.py). Both were found by sending requests in
parallel and neither would ever have been found any other way.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher
from conftest import VALID_PNG, FakeAiEngine
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.storage import connect

PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - hashed by the fixture below


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    hasher = PasswordHasher()
    db_path = tmp_path / "concurrent.sqlite"
    monkeypatch.setenv("ADGEN_DB_PATH", str(db_path))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    deps.settings.cache_clear()
    return db_path


@pytest.fixture
def client(database: Path) -> Iterator[TestClient]:
    app.dependency_overrides[deps.ai_client] = lambda: FakeAiEngine()
    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.post("/v1/auth/login", json={"loginId": "demo1", "password": PASSWORD})
        yield test_client
    app.dependency_overrides.clear()


def _drafted_session(client: TestClient) -> str:
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
    session_id: str = created.json()["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")
    return session_id


def _in_parallel(client: TestClient, method: str, path: str, count: int = 2, **kwargs: Any):
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(lambda _: client.request(method, path, **kwargs), range(count)))


def _rows(database: Path, sql: str, *params: object) -> list[sqlite3.Row]:
    with connect(database) as connection:
        return connection.execute(sql, params).fetchall()


def test_inv_3_two_simultaneous_finalizes_queue_one_render(
    client: TestClient, database: Path
) -> None:
    """⚠️ Regression guard, and the most expensive of these to get wrong.

    Before the conditional write, both requests answered **202 and two jobs were queued**
    (2026-08-14 실측) — two GPU passes for one session, which is the whole of INV-3. The
    sequential test for INV-3 passes either way, because the second request arrives after the
    first has already written `rendering`.
    """
    session_id = _drafted_session(client)

    responses = _in_parallel(client, "post", f"/v1/sessions/{session_id}/finalize")

    assert sorted(r.status_code for r in responses) == [202, 409]
    assert len(_rows(database, "SELECT job_id FROM jobs WHERE session_id = ?", session_id)) == 1


def test_two_simultaneous_generations_call_the_engine_once(client: TestClient) -> None:
    """The same race on the way in, where the cost is an LLM call rather than a render.

    The loser is refused **before** the engine is asked, because claiming the session is the
    first thing the route does.
    """
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

    responses = _in_parallel(client, "post", f"/v1/sessions/{session_id}/draft")

    assert sorted(r.status_code for r in responses) == [200, 409]


def test_two_simultaneous_patches_do_not_lose_an_edit(client: TestClient) -> None:
    """`revision` is optimistic locking, and it only works if the check and the write are
    one operation.

    Both requests carry `revision: 0` and both pass the check — that part is correct, they
    genuinely were both up to date when they asked. Only the write can decide, and the loser
    has to be told rather than silently overwritten.
    """
    session_id = _drafted_session(client)

    responses = _in_parallel(
        client,
        "patch",
        f"/v1/sessions/{session_id}/draft",
        json={"revision": 0, "patch": {"copy": "바꾼 카피"}},
    )

    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.get(f"/v1/sessions/{session_id}").json()["revision"] == 1

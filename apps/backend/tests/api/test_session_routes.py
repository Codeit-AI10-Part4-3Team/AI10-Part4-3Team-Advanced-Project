"""Create a session, list them, read one — through HTTP, as a client sees it.

The three questions this file exists to answer:

1. Do the three outcomes of `POST /v1/sessions` come out the way the contract's table says?
2. Does a session survive a restart? (S2's completion condition, and the reason ADR-0010
   ruled out in-memory storage.)
3. Is someone else's session a 404 rather than a 403? (INV-9.)
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher
from conftest import FILLED_CATEGORY, FILLED_TARGET, FakeAiEngine
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.models import NeedsInput

SECRET = "test-signing-key"  # noqa: S105 - a test fixture, never a deployed key
PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - hashed by the fixture below

# A 1x1 PNG. Real magic bytes, because the format check sniffs the payload rather than
# trusting the filename or the Content-Type — both of which the caller supplies.
PNG = (
    b"\x89PNG\r\n\x1a\n"
    + struct.pack(">I", 13)
    + b"IHDR"
    + struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    + b"\x1f\x15\xc4\x89"
)


@pytest.fixture
def ai() -> FakeAiEngine:
    return FakeAiEngine()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two accounts and a database, as a deployment has them.

    Two because INV-9 needs "someone else" to exist — with one account the 404 path in this
    file could not be written at all.
    """
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "sessions.sqlite"))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", SECRET)
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}},'
        f' {{"login_id": "demo2", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    deps.settings.cache_clear()
    return tmp_path


@pytest.fixture
def client(env: Path, ai: FakeAiEngine) -> Iterator[TestClient]:
    app.dependency_overrides[deps.ai_client] = lambda: ai
    # ⚠️ `https://` base URL, not decoration: the session cookie carries `Secure`, so an
    # http:// test client accepts it and then never sends it back — every request would be
    # 401 and the failure would look like broken auth rather than a test-setup detail.
    with TestClient(app, base_url="https://testserver") as test_client:
        _login(test_client, "demo1")
        yield test_client
    app.dependency_overrides.clear()


def _login(client: TestClient, login_id: str) -> None:
    response = client.post("/v1/auth/login", json={"loginId": login_id, "password": PASSWORD})
    assert response.status_code == 200, response.text


def _create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "outputType": "single_ad",
        "productName": "테스트 제품",
        "sellingPoint": "수분감이 오래 갑니다",
        "note": "",
        **overrides,
    }
    response = client.post(
        "/v1/sessions",
        data=fields,
        files={"productImage": ("photo.png", PNG, "image/png")},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ---- the three outcomes of POST /v1/sessions (contract table) ---------------------------


def test_a_filled_brief_reaches_brief_ready(client: TestClient) -> None:
    body = _create(client)

    assert body["state"] == "brief_ready"
    assert body["messageMode"] == "normal"
    assert body["brief"]["category"] == FILLED_CATEGORY
    assert body["brief"]["target"] == FILLED_TARGET
    assert "needsInput" not in body


def test_needs_input_stays_in_brief_filling_and_is_not_an_error(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """Missing information is a step in the conversation, not a failure (기획서 9.3).

    201 with `needsInput`, and the two inferred fields empty rather than absent — the
    contract has no nulls, so "we could not decide" is `""`.
    """
    ai.needs_input = NeedsInput(field="category", reason="제품군을 판단하지 못했습니다.")

    body = _create(client)

    assert body["state"] == "brief_filling"
    assert body["messageMode"] == "normal"
    assert body["needsInput"]["field"] == "category"
    assert body["brief"]["category"] == ""


def test_an_engine_outage_degrades_instead_of_failing(client: TestClient, ai: FakeAiEngine) -> None:
    """ADR-0005: the one designed degradation in the system.

    ⚠️ Three things at once, and all three matter. Still 201 — an outage in an optional
    inference must not look like a broken product. `degraded` — the mode is a reported
    metric, so a degradation that did not say so would not be counted. And still
    `brief_filling`, **not** `brief_ready`: moving on would let draft generation start with
    an empty category and target, and the brief is the guardrail's evidence.
    """
    ai.available = False

    body = _create(client)

    assert body["state"] == "brief_filling"
    assert body["messageMode"] == "degraded"
    assert body["brief"]["category"] == ""
    assert "needsInput" not in body


def test_the_degraded_and_needs_input_cases_are_told_apart_by_one_key(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """Both sit in `brief_filling`, and the screen has to show different things.

    The contract's discriminator is the presence of `needsInput`, not `messageMode` — this
    pins that the two never collide, because reusing `needsInput` for outages is the obvious
    shortcut and ADR-0005 forbids it.
    """
    ai.available = False
    degraded = _create(client)

    ai.available = True
    ai.needs_input = NeedsInput(field="target", reason="대상을 판단하지 못했습니다.")
    asked = _create(client)

    assert degraded["state"] == asked["state"] == "brief_filling"
    assert "needsInput" not in degraded
    assert "needsInput" in asked


# ---- durability (S2's completion condition, ADR-0010) -----------------------------------


def test_a_session_survives_a_restart(client: TestClient, env: Path, ai: FakeAiEngine) -> None:
    """The reason ADR-0010 ruled out in-memory storage, as a test.

    A second `TestClient` is a second application lifespan against the same file — the
    closest a unit test gets to `docker compose down && up`. If sessions lived in a
    process-local dict this is where "확정을 눌렀는데 결과가 없다" would show up.
    """
    session_id = _create(client)["sessionId"]

    with TestClient(app, base_url="https://testserver") as restarted:
        _login(restarted, "demo1")
        response = restarted.get(f"/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["sessionId"] == session_id


def test_the_image_is_written_to_disk_and_only_its_path_is_stored(
    client: TestClient, env: Path
) -> None:
    """ADR-0010: bytes on disk, path in the row. A photo in a database column would carry
    the whole file into every backup and every read of the session."""
    body = _create(client)

    stored = Path(body["brief"]["productImageUrl"])
    assert stored.exists()
    assert stored.read_bytes() == PNG


# ---- INV-9 -----------------------------------------------------------------------------


def test_inv_9_someone_elses_session_is_404_not_403(client: TestClient, ai: FakeAiEngine) -> None:
    """403 would confirm the id exists, which is what an attacker walking ids wants to know.

    The session is real and the requester is authenticated — the only thing wrong is whose
    it is, and the answer must be identical to the answer for an id that never existed.
    """
    session_id = _create(client)["sessionId"]

    _login(client, "demo2")
    mine = client.get(f"/v1/sessions/{session_id}")
    invented = client.get("/v1/sessions/00000000-0000-4000-8000-000000000000")

    assert mine.status_code == 404
    assert mine.json() == invented.json()


def test_inv_9_the_list_only_shows_your_own(client: TestClient) -> None:
    _create(client)
    _create(client)

    _login(client, "demo2")
    assert client.get("/v1/sessions").json() == []


def test_the_list_is_newest_first_and_carries_no_draft(client: TestClient) -> None:
    """Summaries, not sessions: a list endpoint that shipped every draft would grow without
    bound as work accumulates (contract, `SessionSummary`)."""
    first = _create(client, productName="첫번째")
    second = _create(client, productName="두번째")

    body = client.get("/v1/sessions").json()

    assert [row["sessionId"] for row in body] == [second["sessionId"], first["sessionId"]]
    assert [row["productName"] for row in body] == ["두번째", "첫번째"]
    assert all("draft" not in row for row in body)


# ---- auth and validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/sessions"),
        ("get", "/v1/sessions/00000000-0000-4000-8000-000000000000"),
        ("get", "/v1/templates"),
        ("get", "/v1/art-styles"),
    ],
)
def test_every_session_route_requires_a_session(
    env: Path, ai: FakeAiEngine, method: str, path: str
) -> None:
    """Everything except /health and /v1/auth/* is behind the cookie (API_계약.md 6절)."""
    app.dependency_overrides[deps.ai_client] = lambda: ai
    with TestClient(app, base_url="https://testserver") as anonymous:
        response = anonymous.request(method, path)
    app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_a_non_image_upload_is_422_invalid_image(client: TestClient) -> None:
    """Sniffed from the bytes. A `.png` filename and an `image/png` header are both supplied
    by the caller, so trusting either would make the check check nothing."""
    response = client.post(
        "/v1/sessions",
        data={
            "outputType": "single_ad",
            "productName": "테스트 제품",
            "sellingPoint": "수분감이 오래 갑니다",
        },
        files={"productImage": ("photo.png", b"GIF89a not really a png", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


def test_an_oversized_selling_point_is_refused_rather_than_truncated(client: TestClient) -> None:
    """The contract refuses instead of trimming: silently cutting it means the tail of what
    the user wrote disappears from the ad and nobody can explain why."""
    response = client.post(
        "/v1/sessions",
        data={
            "outputType": "single_ad",
            "productName": "테스트 제품",
            "sellingPoint": "가" * 201,
        },
        files={"productImage": ("photo.png", PNG, "image/png")},
    )

    assert response.status_code == 422


def test_the_catalog_art_styles_are_empty_until_the_decision_lands(client: TestClient) -> None:
    """⚠️ Pinned deliberately. 미결정_대장 A절 3번 is 차단, and the contract says this route's
    shape is fixed while its contents are not. A day when this returns hard-coded candidates
    is a day a blocked decision got made in code instead of in a 회의록."""
    assert client.get("/v1/art-styles").json() == []


def test_the_catalog_offers_both_output_types(client: TestClient) -> None:
    body = client.get("/v1/templates").json()
    assert {row["outputType"] for row in body} == {"comic", "single_ad"}

"""Draft generation, partial replacement, finalize and polling — S3 to S6, through HTTP.

The pass-through test at the top is the one that answers the milestone's question: does a
session get from `created` to a queued render without anyone stepping outside the contract?
Everything below it is a failure path, and the failure paths are where the design lives —
what unlocks, what does not, and what a second attempt is told.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher
from conftest import VALID_PNG as PNG
from conftest import FakeAiEngine
from fastapi.testclient import TestClient

from api import deps
from api.main import app

PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - hashed by the fixture below


@pytest.fixture
def ai() -> FakeAiEngine:
    return FakeAiEngine()


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ai: FakeAiEngine
) -> Iterator[TestClient]:
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "flow.sqlite"))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}},'
        f' {{"login_id": "demo2", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    deps.settings.cache_clear()

    app.dependency_overrides[deps.ai_client] = lambda: ai
    # https:// because the session cookie carries `Secure` — see test_session_routes.py.
    with TestClient(app, base_url="https://testserver") as test_client:
        response = test_client.post(
            "/v1/auth/login", json={"loginId": "demo1", "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        yield test_client
    app.dependency_overrides.clear()


def _create(client: TestClient, output_type: str = "single_ad") -> dict[str, Any]:
    response = client.post(
        "/v1/sessions",
        data={
            "outputType": output_type,
            "productName": "테스트 제품",
            "sellingPoint": "수분감이 오래 갑니다",
            "note": "",
        },
        files={"productImage": ("photo.png", PNG, "image/png")},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ---- the pass-through ------------------------------------------------------------------


def test_a_session_walks_from_created_to_a_queued_render(client: TestClient) -> None:
    """`created` -> `brief_ready` -> `draft_ready` -> `rendering`, all through the contract.

    This is the milestone's question in one test. Every step is a route a client can call;
    nothing here reaches into the domain to move a session along, because a pass-through
    that needed a shortcut would not be a pass-through.
    """
    session_id = _create(client)["sessionId"]

    drafted = client.post(f"/v1/sessions/{session_id}/draft")
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["state"] == "draft_ready"
    assert drafted.json()["draft"]["copy"] == "[더미] 카피"

    accepted = client.post(f"/v1/sessions/{session_id}/finalize")
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["jobId"]
    assert accepted.json()["statusUrl"] == f"/v1/jobs/{job_id}"

    assert client.get(f"/v1/sessions/{session_id}").json()["state"] == "rendering"

    polled = client.get(f"/v1/jobs/{job_id}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "queued"
    # The server sets the interval; a client that hard-coded one could not be slowed down.
    assert polled.headers["Retry-After"] == "3"


def test_a_comic_session_carries_six_panels_through(client: TestClient) -> None:
    """INV-1 across the seam: the output type decides the draft's shape, and the engine is
    told which one rather than guessing from the brief."""
    session_id = _create(client, output_type="comic")["sessionId"]

    body = client.post(f"/v1/sessions/{session_id}/draft").json()

    assert len(body["draft"]["panels"]) == 6
    # `role` follows `index` (INV-5), so the whole sequence is pinned, not just the first.
    assert [panel["role"] for panel in body["draft"]["panels"]] == [
        "hook",
        "setup",
        "problem",
        "solution",
        "proof",
        "cta",
    ]


# ---- INV-7 and the ADR-0012 unlock ------------------------------------------------------


def test_inv_7_the_brief_locks_once_a_draft_exists(client: TestClient) -> None:
    """A brief patch after generation is a 409, because the draft's evidence would move."""
    session_id = _create(client)["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")

    response = client.patch(
        f"/v1/sessions/{session_id}/brief",
        json={"revision": 0, "patch": {"sellingPoint": "다른 소구점"}},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"


def test_inv_7_holds_even_when_the_patch_leaves_the_brief_incomplete(client: TestClient) -> None:
    """⚠️ Regression guard. The test above sends a *complete* patch and passes for a reason
    that does not generalise — its target was `brief_ready`, which `draft_ready` cannot
    reach. An **incomplete** patch used to target `session.state` instead, and
    `draft_ready -> draft_ready` is a legal edge (draft patches repeat), so the guard had
    nothing to refuse: the request came back **200 and overwrote the brief a draft was
    already built on** (2026-08-14 실측).

    Emptying `category` is the cheapest way to express "incomplete"; the hole was in the
    target selection, not in this particular field.
    """
    session_id = _create(client)["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")
    before = client.get(f"/v1/sessions/{session_id}").json()

    response = client.patch(
        f"/v1/sessions/{session_id}/brief",
        json={"revision": 0, "patch": {"category": ""}},
    )

    assert response.status_code == 409
    after = client.get(f"/v1/sessions/{session_id}").json()
    assert after["brief"] == before["brief"]
    assert after["revision"] == before["revision"]


@pytest.mark.parametrize("path", ["brief", "draft"])
def test_an_empty_patch_is_refused_rather_than_burning_a_revision(
    client: TestClient, path: str
) -> None:
    """`minProperties: 1`, and it is not pedantry.

    An empty patch changes nothing and still increments `revision` — the value every other
    open screen is holding. One no-op invalidates their optimistic lock and their next real
    edit comes back 409 for no reason anyone can see.
    """
    session_id = _create(client)["sessionId"]
    if path == "draft":
        client.post(f"/v1/sessions/{session_id}/draft")

    response = client.patch(f"/v1/sessions/{session_id}/{path}", json={"revision": 0, "patch": {}})

    assert response.status_code == 422
    assert client.get(f"/v1/sessions/{session_id}").json()["revision"] == 0


def test_a_failed_generation_unlocks_the_brief_and_can_be_retried(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """ADR-0012, and the reason it exists.

    ⚠️ Without the unlock this session is stuck for good: the brief is locked because
    generation started, and there is no draft to justify the lock. Nothing the user could
    do would move it — which is why the failing path is tested as far as a **successful
    retry**, not just as far as the error code.
    """
    session_id = _create(client)["sessionId"]
    ai.available = False

    failed = client.post(f"/v1/sessions/{session_id}/draft")
    assert failed.status_code == 503
    assert failed.json()["code"] == "UPSTREAM_UNAVAILABLE"

    back = client.get(f"/v1/sessions/{session_id}").json()
    assert back["state"] == "brief_ready"

    corrected = client.patch(
        f"/v1/sessions/{session_id}/brief",
        json={"revision": 0, "patch": {"sellingPoint": "더 구체적인 소구점"}},
    )
    assert corrected.status_code == 200, corrected.text

    ai.available = True
    assert client.post(f"/v1/sessions/{session_id}/draft").json()["state"] == "draft_ready"


def test_a_refusal_is_422_and_also_unlocks(client: TestClient, ai: FakeAiEngine) -> None:
    """The guardrail declining is the design working (INV-6), not an error to retry around
    — but the session must still be correctable, so this path unlocks too."""
    session_id = _create(client)["sessionId"]
    ai.refuses = True

    response = client.post(f"/v1/sessions/{session_id}/draft")

    assert response.status_code == 422
    assert response.json()["code"] == "CONTENT_POLICY_REJECTED"
    assert client.get(f"/v1/sessions/{session_id}").json()["state"] == "brief_ready"


# ---- S5 부분 교체 -------------------------------------------------------------------------


def test_a_patch_changes_only_what_it_names(client: TestClient) -> None:
    """The point of 부분 교체, and the thing a careless implementation loses.

    `visualPlan` is not in the patch, so it has to come back byte-identical. A route that
    regenerated the draft would pass an assertion on `copy` alone.
    """
    session_id = _create(client)["sessionId"]
    before = client.post(f"/v1/sessions/{session_id}/draft").json()["draft"]

    body = client.patch(
        f"/v1/sessions/{session_id}/draft",
        json={"revision": 0, "patch": {"copy": "바꾼 카피"}},
    ).json()

    assert body["draft"]["copy"] == "바꾼 카피"
    assert body["draft"]["visualPlan"] == before["visualPlan"]
    assert body["draft"]["adPlan"] == before["adPlan"]
    assert body["revision"] == 1


def test_a_panel_patch_addresses_one_cell_by_index(client: TestClient) -> None:
    session_id = _create(client, output_type="comic")["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")

    body = client.patch(
        f"/v1/sessions/{session_id}/draft",
        json={"revision": 0, "patch": {"panels": {"4": {"dialogue": "이거면 아침이 편해져요"}}}},
    ).json()

    panels = body["draft"]["panels"]
    assert panels[3]["dialogue"] == "이거면 아침이 편해져요"
    assert panels[3]["scene"] == "[더미] 장면 4"
    assert panels[2]["dialogue"] == "[더미] 대사 3"


@pytest.mark.parametrize(
    "patch",
    [{"adPlan": "다른 기획안"}, {"panels": {"1": {"role": "cta"}}}],
    ids=["INV-8 adPlan", "INV-5 role"],
)
def test_the_read_only_fields_cannot_be_patched(client: TestClient, patch: dict[str, Any]) -> None:
    """INV-8 and INV-5, enforced by the schema having no such field rather than by a check.

    An unknown field is a 422 — which means a future edit cannot forget the rule, because
    there is nothing to forget: the field would have to be *added* to break it.
    """
    session_id = _create(client, output_type="comic")["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")

    response = client.patch(
        f"/v1/sessions/{session_id}/draft", json={"revision": 0, "patch": patch}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("output_type", "patch"),
    [
        ("single_ad", {"panels": {"4": {"dialogue": "새 대사"}}}),
        ("single_ad", {"panels": {"4": {"dialogue": "새 대사"}}, "copy": "새 카피"}),
        ("comic", {"copy": "새 카피"}),
        ("comic", {"visualPlan": "새 비주얼"}),
    ],
    ids=["single_ad + panels", "single_ad + panels and copy", "comic + copy", "comic + visualPlan"],
)
def test_a_patch_naming_the_other_output_types_fields_is_refused(
    client: TestClient, output_type: str, patch: dict[str, Any]
) -> None:
    """⚠️ `DraftPatch` carries every output type's fields and has no `outputType`, so this is
    a request a client can make while following the contract — the same hole the brief patch
    had with `character` and `aspectRatio`.

    Two things have to hold, and the second is the reason the check is here rather than only
    on the engine. **422, not 200**: before 2026-08-18 the engine dropped the field that did
    not apply and answered 200 with a draft that had not changed, so the caller was told its
    request succeeded. **422, not 503**: `ai_client` maps every HTTP failure from the engine
    to `AiEngineUnavailableError`, so a 422 raised over there reaches the user as
    `UPSTREAM_UNAVAILABLE` — pointing at a healthy service instead of at the request.
    """
    session_id = _create(client, output_type=output_type)["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")

    response = client.patch(
        f"/v1/sessions/{session_id}/draft", json={"revision": 0, "patch": patch}
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INVALID_REQUEST"

    # The draft is untouched and the revision did not move — a refused patch costs nothing.
    session = client.get(f"/v1/sessions/{session_id}").json()
    assert session["revision"] == 0


def test_a_stale_revision_is_refused(client: TestClient) -> None:
    """Optimistic locking. Two screens open on one session both hold `revision: 0`; without
    this the second save discards the first person's edit and nobody finds out."""
    session_id = _create(client)["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")
    client.patch(
        f"/v1/sessions/{session_id}/draft", json={"revision": 0, "patch": {"copy": "첫번째"}}
    )

    response = client.patch(
        f"/v1/sessions/{session_id}/draft", json={"revision": 0, "patch": {"copy": "두번째"}}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "REVISION_CONFLICT"


def test_a_failed_patch_leaves_the_draft_alone(client: TestClient, ai: FakeAiEngine) -> None:
    """⚠️ The opposite of the generation path, deliberately. There *is* something to fall
    back to here — the existing draft — so nothing unlocks and nothing moves."""
    session_id = _create(client)["sessionId"]
    before = client.post(f"/v1/sessions/{session_id}/draft").json()
    ai.available = False

    response = client.patch(
        f"/v1/sessions/{session_id}/draft", json={"revision": 0, "patch": {"copy": "바꾼 카피"}}
    )

    assert response.status_code == 503
    after = client.get(f"/v1/sessions/{session_id}").json()
    assert after["state"] == "draft_ready"
    assert after["draft"] == before["draft"]
    assert after["revision"] == before["revision"]


# ---- S6 확정, INV-2 and INV-3 -----------------------------------------------------------


def test_inv_3_a_session_can_only_be_finalized_once(client: TestClient) -> None:
    """One render per session — the cost defence, in code rather than in a document."""
    session_id = _create(client)["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")
    assert client.post(f"/v1/sessions/{session_id}/finalize").status_code == 202

    second = client.post(f"/v1/sessions/{session_id}/finalize")

    assert second.status_code == 409
    assert second.json()["code"] == "STATE_CONFLICT"


def test_inv_2_the_draft_cannot_be_patched_after_finalize(client: TestClient) -> None:
    """ "확정 후 재생성 없음" (기획서 5.1) as a state, not as a screen convention."""
    session_id = _create(client)["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")
    client.post(f"/v1/sessions/{session_id}/finalize")

    response = client.patch(
        f"/v1/sessions/{session_id}/draft", json={"revision": 0, "patch": {"copy": "늦은 수정"}}
    )

    assert response.status_code == 409


def test_finalizing_before_a_draft_exists_is_409(client: TestClient) -> None:
    session_id = _create(client)["sessionId"]

    response = client.post(f"/v1/sessions/{session_id}/finalize")

    assert response.status_code == 409


def test_inv_9_someone_elses_job_is_404(client: TestClient) -> None:
    """A `jobId` is guessable in exactly the way a `sessionId` is."""
    session_id = _create(client)["sessionId"]
    client.post(f"/v1/sessions/{session_id}/draft")
    job_id = client.post(f"/v1/sessions/{session_id}/finalize").json()["jobId"]

    client.post("/v1/auth/login", json={"loginId": "demo2", "password": PASSWORD})
    response = client.get(f"/v1/jobs/{job_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"

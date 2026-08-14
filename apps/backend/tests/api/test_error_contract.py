"""Every error a client can provoke, in the contract's shape.

⚠️ These assert the **body**, not just the status. That distinction is the whole reason this
file exists: `POST /v1/auth/login` without a password answered 422 with FastAPI's own
`{"detail": [...]}` and no `code` at all, and every existing test passed because they all
checked `status_code == 422` and stopped there (2026-08-14 실측, 코드 리뷰).

`errors.py` states the premise — "clients branch on `code`, so it has to survive all the way
to the wire" — and the most-travelled error path was the one where it did not.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher
from conftest import VALID_PNG, FakeAiEngine
from fastapi.testclient import TestClient

from api import deps
from api.main import app

PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - hashed by the fixture below


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "errors.sqlite"))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    deps.settings.cache_clear()
    app.dependency_overrides[deps.ai_client] = lambda: FakeAiEngine()
    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.post("/v1/auth/login", json={"loginId": "demo1", "password": PASSWORD})
        yield test_client
    app.dependency_overrides.clear()


def _session(client: TestClient, output_type: str) -> str:
    created = client.post(
        "/v1/sessions",
        data={
            "outputType": output_type,
            "productName": "테스트 제품",
            "sellingPoint": "수분감이 오래 갑니다",
            "note": "",
        },
        files={"productImage": ("photo.png", VALID_PNG, "image/png")},
    )
    return str(created.json()["sessionId"])


def test_a_malformed_body_carries_the_contract_error_code(client: TestClient) -> None:
    """⚠️ Regression guard. The API's most common error had no `code` at all."""
    response = client.post("/v1/auth/login", json={"loginId": "demo1"})

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_a_validation_error_never_echoes_the_value_it_rejected(client: TestClient) -> None:
    """⚠️ pydantic's own detail embeds the offending **input**, and on this route that input
    is a plaintext password. Forwarding it would put one in a response body and in every log
    that records bodies — the exact accident 세션_보관_정책 1.2절 names."""
    response = client.post("/v1/auth/login", json={"loginId": "demo1", "password": 12345})

    body = response.text
    assert "12345" not in body
    # The field name is useful and safe; the value is neither.
    assert "password" in response.json()["message"]


@pytest.mark.parametrize(
    ("output_type", "patch"),
    [
        ("comic", {"aspectRatio": "1:1"}),
        ("single_ad", {"character": {"appearance": "a", "outfit": "b"}}),
    ],
    ids=["aspectRatio on a comic", "character on a single ad"],
)
def test_a_field_that_does_not_apply_to_the_output_type_is_422(
    client: TestClient, output_type: str, patch: dict[str, Any]
) -> None:
    """⚠️ Regression guard. `BriefPatch` carries both fields and cannot know the output
    type, so a client following the contract can send either — and the pairing check raises
    a plain `ValueError`, which escaped the route's guard as a **500** (실측).

    The contract's answer is 422 `INVALID_REQUEST`, and the message names the field.
    """
    session_id = _session(client, output_type)

    response = client.patch(
        f"/v1/sessions/{session_id}/brief", json={"revision": 0, "patch": patch}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_an_unknown_field_on_a_patch_is_422_with_a_code(client: TestClient) -> None:
    """The claim `models/patch.py` makes about INV-8, checked as far as the body.

    It said naming `adPlan` is "a 422 `INVALID_REQUEST` — the contract's answer". It was a
    422 with a different body until the validation handler landed.
    """
    session_id = _session(client, "single_ad")
    client.post(f"/v1/sessions/{session_id}/draft")

    response = client.patch(
        f"/v1/sessions/{session_id}/draft",
        json={"revision": 0, "patch": {"adPlan": "다른 기획안"}},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_a_bad_path_parameter_is_still_the_contract_shape(client: TestClient) -> None:
    """`sessionId` is a UUID in the contract; anything else never reaches a handler."""
    response = client.get("/v1/sessions/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"

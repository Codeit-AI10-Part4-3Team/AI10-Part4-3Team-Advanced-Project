"""HTTP surface: contract shape and status codes.

Convention: tests/ mirrors src/ (src/api/main.py -> tests/api/test_main.py).
"""

from conftest import GROUNDED_TEXT, FakeAiEngine
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_returns_contract_shape(client: TestClient) -> None:
    response = client.post("/v1/ask", json={"question": "어디로 가야 하나요?"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"text", "messageMode", "sources"}
    assert body["messageMode"] == "grounded"
    assert body["text"] == GROUNDED_TEXT
    assert set(body["sources"][0]) == {"title", "quote", "url"}


def test_engine_outage_still_answers(client: TestClient, ai: FakeAiEngine) -> None:
    """A dead engine degrades the answer; it does not fail the request."""
    ai.available = False
    response = client.post("/v1/ask", json={"question": "어디로 가야 하나요?"})
    assert response.status_code == 200
    assert response.json()["messageMode"] == "official_fallback"


def test_unknown_field_is_rejected(client: TestClient) -> None:
    """A typo'd field that is silently ignored is worse than a 422 — the caller never learns."""
    response = client.post("/v1/ask", json={"question": "안녕", "locales": "ko"})
    assert response.status_code == 422


def test_error_body_uses_the_contract_shape(client: TestClient) -> None:
    """Clients branch on `code`; FastAPI's default `{"detail": ...}` would break them."""
    response = client.get("/v1/nonexistent")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message"}
    assert response.json()["code"] == "NOT_FOUND"

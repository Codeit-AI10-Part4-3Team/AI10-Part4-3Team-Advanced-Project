"""Contract conformance for the HTTP surface.

Asserts the wire shape promised by packages/contracts/openapi.yaml: camelCase keys, keys
that must exist even when null, 200-for-refusal semantics, and the absence of a retrieval
endpoint. Module behaviour is covered in test_generation.py / test_retrieval.py.
"""

import pytest
from conftest import ANSWERABLE_QUESTION, UNANSWERABLE_QUESTION
from fastapi.testclient import TestClient

from ai_engine.service import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_returns_contract_shape(client: TestClient) -> None:
    response = client.post("/v1/generate", json={"question": ANSWERABLE_QUESTION})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "sources", "refusalReason", "guardrailApplied"}
    assert body["answer"] is not None
    assert set(body["sources"][0]) == {"title", "quote", "url"}
    assert body["refusalReason"] is None


def test_refusal_keeps_the_null_answer_key(client: TestClient) -> None:
    """`answer: null` is a normal refusal — omitting the key would hide it as a bug."""
    response = client.post("/v1/generate", json={"question": UNANSWERABLE_QUESTION})
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body and body["answer"] is None
    assert body["refusalReason"] == "no_evidence"


def test_unknown_field_is_rejected(client: TestClient) -> None:
    """A typo'd field that is silently ignored makes the caller think it was sent."""
    response = client.post("/v1/generate", json={"question": "안녕", "locales": "ko"})
    assert response.status_code == 422


def test_retrieval_is_not_exposed(client: TestClient) -> None:
    """Retrieval is a stage in a one-way pipeline, not a public entry point.

    ⚠️ An exact set, not a membership check. Listing what may exist is what makes a new
    route someone added "for debugging" fail here instead of shipping — inviting callers
    into the middle of the pipeline is the thing this test guards.

    `/v1/generate` is the template question-and-answer path and leaves with the seam swap.
    """
    assert set(client.get("/openapi.json").json()["paths"]) == {
        "/health",
        "/v1/generate",
        "/v1/brief:fill",
        "/v1/draft:generate",
        "/v1/image:render",
    }

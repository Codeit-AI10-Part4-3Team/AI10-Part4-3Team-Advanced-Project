"""Starter harness tests — they prove the E2E wiring itself works.

Replace/extend with your real 관통 시나리오 and its failure modes. Keep this file's
contract: reach services over HTTP, never import app packages.
"""

import httpx
import pytest


@pytest.mark.flow
def test_backend_is_reachable(client: httpx.Client) -> None:
    """Smallest possible end-to-end assertion: the stack is up and answering.

    Everything downstream depends on this, so a failure here should be read as "the stack
    did not come up", not as a feature bug.
    """
    response = client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json().get("status") == "ok"


@pytest.mark.flow
def test_ask_threads_the_whole_stack(client: httpx.Client) -> None:
    """One request crosses backend -> ai-engine -> back, and always returns something usable."""
    response = client.post("/v1/ask", json={"question": "환불은 어떻게 하나요?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"]
    assert body["messageMode"] in {"grounded", "official_fallback"}


@pytest.mark.failure
def test_unknown_path_uses_the_contract_error_shape(client: httpx.Client) -> None:
    """Clients branch on `code`; a stray FastAPI `{"detail": ...}` would break them."""
    response = client.get("/v1/definitely-not-a-route")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message"}

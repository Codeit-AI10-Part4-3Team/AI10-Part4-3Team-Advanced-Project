"""Harness tests — they prove the E2E wiring itself works, not that a feature does.

⚠️ **This file is deliberately feature-free.** It used to thread the stack through the
template's `/v1/ask`; that route was deleted (API_계약.md 7절) and the crossing it proved
(backend -> ai-engine -> back) is now covered by `test_ad_flow.py` on the contract path,
which is the one that has to keep working.

Keep this file's contract: reach services over HTTP, never import app packages.
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


@pytest.mark.failure
def test_unknown_path_uses_the_contract_error_shape(client: httpx.Client) -> None:
    """Clients branch on `code`; a stray FastAPI `{"detail": ...}` would break them."""
    response = client.get("/v1/definitely-not-a-route")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message"}

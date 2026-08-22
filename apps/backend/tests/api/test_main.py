"""HTTP surface: contract shape and status codes.

Convention: tests/ mirrors src/ (src/api/main.py -> tests/api/test_main.py).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from api import deps


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_field_is_rejected(client: TestClient) -> None:
    """A typo'd field that is silently ignored is worse than a 422 — the caller never learns.

    On `/v1/auth/login` because it is the only contract path reachable without a session:
    this asserts a property of the schema layer (`extra="forbid"`), not of authentication,
    so it must not need a logged-in client to run. The credentials are deliberately wrong —
    the 422 has to arrive from validation, before anything looks at them.
    """
    response = client.post(
        "/v1/auth/login", json={"loginId": "nobody", "password": "x", "locales": "ko"}
    )
    assert response.status_code == 422


def test_error_body_uses_the_contract_shape(client: TestClient) -> None:
    """Clients branch on `code`; FastAPI's default `{"detail": ...}` would break them."""
    response = client.get("/v1/nonexistent")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message"}
    assert response.json()["code"] == "NOT_FOUND"


def test_a_trailing_slash_is_404_and_never_a_redirect(client: TestClient) -> None:
    """A slash redirect would hand the caller an absolute `http://` URL, downgrading TLS.

    Starlette builds that redirect from `scope["scheme"]`, which is always `http` behind our
    proxy chain: the frontend nginx overwrites `X-Forwarded-Proto` with its own plaintext
    `$scheme`, and uvicorn runs without `--proxy-headers`. With TLS terminating at the front
    proxy (ADR-0016), `POST /v1/auth/login/` would answer `307 Location: http://.../login`,
    and 307 preserves method and body — so the password leaves once in the clear. The proxy
    redirects it back to HTTPS and the request succeeds, which is why nothing shows on
    screen (issue #129).

    ⚠️ This asserts the *absence* of a redirect, so it fails the moment someone restores
    `redirect_slashes`. Checking only the 404 would not: a 307 followed by the redirect would
    also end at a 404 for an unauthenticated caller.
    """
    response = client.post(
        "/v1/auth/login/",
        json={"loginId": "demo1", "password": "pw"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert "location" not in response.headers
    assert response.json()["code"] == "NOT_FOUND"


def test_startup_installs_the_operational_log(client: TestClient) -> None:
    """Starting the app has to put the log where a deploy cannot erase it.

    ⚠️ **This is the only test that holds the wiring.** Every other observability test calls
    `install_file_log` itself, so deleting the call in `api.main.lifespan` left the whole
    suite green — found by removing it and watching nothing break (2026-08-21 변이 시험).
    What would have happened in deployment is that measurements kept going to stdout only,
    and the 30-day period in 세션_보관_정책 2절 would have quietly stayed at "one deploy".

    `client` enters `TestClient` as a context manager, which is what runs `lifespan`.
    """
    log_dir = Path(deps.settings().log_dir)

    assert (log_dir / "app.log").exists(), (
        f"{log_dir} 에 app.log 가 없습니다. api.main.lifespan 의 install_file_log 호출을 보세요."
    )

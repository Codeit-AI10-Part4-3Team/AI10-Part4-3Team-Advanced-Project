"""The auth routes end to end, through the real app.

These are the S0 completion checks (구현_범위.md): two fixed accounts, id lookup, password
comparison, session cookie, and 401 for an unauthenticated request. What they are not is the
INV-9 test — "someone else's session is a 404" needs a session resource, which arrives with
S2. What lands here is the half S0 owns: the request is resolved to *an* owner, and requests
without one are turned away.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.config import SESSION_COOKIE_NAME

PLAINTEXT_DEMO1 = "correct-horse-battery-staple"
PLAINTEXT_DEMO2 = "not-the-one"
SECRET = "test-signing-key"  # noqa: S105 - a test fixture, not a credential


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A running app with the two fixed accounts seeded, as a deployment would have them."""
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "auth.sqlite"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", SECRET)
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        json.dumps(
            [
                {"login_id": "demo1", "password_hash": hasher.hash(PLAINTEXT_DEMO1)},
                {"login_id": "demo2", "password_hash": hasher.hash(PLAINTEXT_DEMO2)},
            ]
        ),
    )
    deps.settings.cache_clear()

    # base_url is https so the test client will send back a `Secure` cookie; the route sets
    # `Secure` unconditionally because login carries a password (see routes/auth.py).
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def _login(client: TestClient, login_id: str, password: str):
    return client.post("/v1/auth/login", json={"loginId": login_id, "password": password})


# ---- 로그인 --------------------------------------------------------------------------


def test_login_with_the_right_password_succeeds(client: TestClient) -> None:
    response = _login(client, "demo1", PLAINTEXT_DEMO1)

    assert response.status_code == 200
    assert response.json()["loginId"] == "demo1"
    assert SESSION_COOKIE_NAME in response.cookies


def test_login_never_returns_the_password_hash(client: TestClient) -> None:
    """The hash has no field on `Me` to land in, but a route that built the response by
    hand could still put it there. This is the check that would notice."""
    body = _login(client, "demo1", PLAINTEXT_DEMO1).json()

    assert set(body) == {"userId", "loginId", "createdAt"}


def test_the_session_cookie_carries_the_contract_attributes(client: TestClient) -> None:
    """`session_token=<token>; HttpOnly; Secure; SameSite=Lax; Max-Age=86400` (계약 6절).

    HttpOnly is what keeps one XSS from handing over the session, so it is checked on the
    wire rather than trusted to the framework's defaults.
    """
    header = _login(client, "demo1", PLAINTEXT_DEMO1).headers["set-cookie"]

    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=lax" in header.replace("SameSite=Lax", "SameSite=lax")
    assert "Max-Age=86400" in header


def test_responses_carrying_identity_are_not_cacheable(client: TestClient) -> None:
    """`Cache-Control: no-store` on login and on everything behind `current_user`.

    Login's response carries the session token in `Set-Cookie` and `/v1/me` carries one
    person's identity. Whether a reverse proxy sits in front of us is still an open decision
    (API_계약.md 2절, 소관 05), so the header has to be right before one appears — a cache
    handing user A's response to user B is not a failure that shows up in testing.
    """
    login = _login(client, "demo1", PLAINTEXT_DEMO1)
    me = client.get("/v1/me")

    assert login.headers.get("cache-control") == "no-store"
    assert me.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize(
    ("login_id", "password"),
    [("demo1", PLAINTEXT_DEMO2), ("no-such-user", PLAINTEXT_DEMO1)],
    ids=["wrong password", "unknown login id"],
)
def test_both_login_failures_answer_identically(
    client: TestClient, login_id: str, password: str
) -> None:
    """⚠️ The point of this test is that the two rows are indistinguishable. Status, code
    and message must all match: any difference tells an attacker which login ids exist
    (세션_보관_정책.md 1.2절)."""
    response = _login(client, login_id, password)

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIALS",
        "message": "아이디 또는 비밀번호가 올바르지 않습니다.",
    }
    assert SESSION_COOKIE_NAME not in response.cookies


def test_a_malformed_login_body_is_422_not_401(client: TestClient) -> None:
    """A nonsense body and wrong credentials are different answers, not two spellings."""
    assert client.post("/v1/auth/login", json={"loginId": "demo1"}).status_code == 422


# ---- 보호된 경로 ---------------------------------------------------------------------


def test_me_requires_a_session(client: TestClient) -> None:
    response = client.get("/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_me_returns_the_logged_in_account(client: TestClient) -> None:
    _login(client, "demo1", PLAINTEXT_DEMO1)
    response = client.get("/v1/me")

    assert response.status_code == 200
    assert response.json()["loginId"] == "demo1"


def test_two_accounts_get_different_user_ids(client: TestClient) -> None:
    """The precondition INV-9 rests on. If both fixed accounts resolved to the same
    `userId`, ownership checks would pass for the wrong person and the 404 path in S2 would
    never be taken (ADR-0008, 구현_범위.md S0)."""
    first = _login(client, "demo1", PLAINTEXT_DEMO1).json()["userId"]
    client.post("/v1/auth/logout")
    second = _login(client, "demo2", PLAINTEXT_DEMO2).json()["userId"]

    assert first != second


@pytest.mark.parametrize(
    "cookie",
    ["", "garbage", "not.a.real.token"],
    ids=["empty", "garbage", "token-shaped garbage"],
)
def test_a_forged_cookie_is_rejected(client: TestClient, cookie: str) -> None:
    """Every shape of bad cookie ends at the same 401 — the token layer refuses to say
    which kind of bad it was (backend_core/tokens.verify)."""
    response = client.get("/v1/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_a_token_signed_with_another_key_is_rejected(client: TestClient) -> None:
    """The case that matters most: a well-formed token from somewhere else. If this passed,
    anyone who could mint tokens could be any user."""
    from backend_core import tokens

    forged = tokens.issue("00000000-0000-4000-8000-000000000000", "not-our-key", 86400)
    response = client.get("/v1/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={forged}"})

    assert response.status_code == 401


# ---- 로그아웃 ------------------------------------------------------------------------


def test_logout_clears_the_cookie_and_ends_the_session(client: TestClient) -> None:
    _login(client, "demo1", PLAINTEXT_DEMO1)

    response = client.post("/v1/auth/logout")

    assert response.status_code == 204
    assert client.get("/v1/me").status_code == 401


def test_logout_without_a_session_is_401(client: TestClient) -> None:
    """The contract documents a 401 here. A logout that answered 204 to anyone would be a
    route that does nothing, reachable by everyone."""
    assert client.post("/v1/auth/logout").status_code == 401


# ---- 계약에만 있고 구현하지 않는 것 (ADR-0008) ---------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/v1/auth/signup"), ("delete", "/v1/me"), ("patch", "/v1/me/password")],
    ids=["signup", "withdraw", "change password"],
)
def test_the_unimplemented_routes_answer_501(client: TestClient, method: str, path: str) -> None:
    """501, not 404 and not 200. 404 is indistinguishable from a typo in the path; 200 makes
    an undone thing look done (ADR-0008)."""
    _login(client, "demo1", PLAINTEXT_DEMO1)

    response = client.request(method, path)

    assert response.status_code == 501
    assert response.json()["code"] == "NOT_IMPLEMENTED"


def test_signup_is_reachable_while_logged_out(client: TestClient) -> None:
    """⚠️ The contract marks this one `security: []` and the other two deliberately not.

    Gating signup behind a login would put the 501 behind a login screen — unreachable by
    anyone who could actually want it, because you cannot be logged in to create an account.
    """
    response = client.post("/v1/auth/signup")

    assert response.status_code == 501
    assert response.json()["code"] == "NOT_IMPLEMENTED"


@pytest.mark.parametrize(
    ("method", "path"),
    [("delete", "/v1/me"), ("patch", "/v1/me/password")],
    ids=["withdraw", "change password"],
)
def test_the_me_routes_require_a_session_even_though_they_are_501(
    client: TestClient, method: str, path: str
) -> None:
    """⚠️ Regression guard (PR #84 리뷰, 신호정). These two inherit the contract's global
    `security: [sessionCookie]` and have **no** `security: []` exception — only `signup`
    does.

    Answering 501 to anonymous callers was harmless today and that is precisely the risk:
    the day someone implements withdrawal, nothing would have reminded them that deleting
    an account has to know whose account it is. The security scheme and the status code
    answer different questions — 501 is "the server does not do this yet", `security` is
    "who may ask".
    """
    response = client.request(method, path)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"

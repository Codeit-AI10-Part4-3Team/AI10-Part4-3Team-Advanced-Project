"""Shared fixtures for the cross-app E2E harness.

The harness talks to running services over HTTP only — never import `api`,
`backend_core` or `ai_engine` here (app-boundary rule, see e2e/README.md).
"""

import io
import os

import httpx
import pytest
from PIL import Image

BASE_URL_ENV = "E2E_BASE_URL"
WEB_URL_ENV = "E2E_WEB_URL"
LOGIN_ID_ENV = "E2E_LOGIN_ID"
# 아래 두 줄의 억제는 값이 아니라 **이름** 때문입니다. bandit 은 `PASSWORD` 가 들어간 변수에
# 붙은 문자열을 자격 증명으로 읽는데, 여기 있는 것은 읽어 올 환경변수의 이름입니다. 진짜
# 자격 증명은 이 저장소 어디에도 없습니다 (CI 가 잡 안에서 만들어 넣습니다).
PASSWORD_ENV = "E2E_PASSWORD"  # noqa: S105 - env var name, not a credential
OTHER_LOGIN_ID_ENV = "E2E_OTHER_LOGIN_ID"
OTHER_PASSWORD_ENV = "E2E_OTHER_PASSWORD"  # noqa: S105 - env var name, not a credential


@pytest.fixture(scope="session")
def base_url() -> str:
    """Backend entry point under test.

    Skips the whole harness when unset so that "wired up but no stack yet" stays
    green in CI — the workflow flips to real verification the moment
    infra/docker-compose.yml can bring the stack up.
    """
    url = os.environ.get(BASE_URL_ENV)
    if not url:
        pytest.skip(f"{BASE_URL_ENV} 미설정 — 스택이 기동된 환경에서만 실행됩니다")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def web_url() -> str:
    """Origin the **browser** talks to — the frontend, not the backend.

    ⚠️ Deliberately a separate variable from `E2E_BASE_URL`. The two can be the same host
    once a proxy fronts the stack (ADR-0016), but they are different questions: one is
    "where does the API answer", the other is "what does a person type into a browser".
    Collapsing them hides the day they diverge, which is exactly when a login stops working.
    """
    url = os.environ.get(WEB_URL_ENV)
    if not url:
        pytest.skip(f"{WEB_URL_ENV} 미설정 — 프론트엔드가 기동된 환경에서만 실행됩니다")
    return url.rstrip("/")


def _credentials(login_id_env: str, password_env: str) -> tuple[str, str]:
    login_id = os.environ.get(login_id_env)
    password = os.environ.get(password_env)
    if not login_id or not password:
        pytest.skip(f"{login_id_env} / {password_env} 미설정 — 계정이 시드된 스택에서만 실행됩니다")
    return login_id, password


@pytest.fixture(scope="session")
def credentials() -> tuple[str, str]:
    """The account the happy path runs as.

    ⚠️ Never hard-code these. 가입 경로가 501이라 계정은 `ADGEN_ACCOUNTS` 시드로만 들어오고
    (ADR-0008), 이 저장소는 public 입니다. CI 는 잡 안에서 임시 계정을 만들어 넣습니다
    (.github/workflows/e2e.yml) — 커밋되는 자격 증명이 하나도 없다는 것이 요점입니다.
    """
    return _credentials(LOGIN_ID_ENV, PASSWORD_ENV)


@pytest.fixture(scope="session")
def other_credentials() -> tuple[str, str]:
    """The second account. **This is what makes INV-9 testable.**

    계정이 하나면 "남의 세션"이 존재하지 않아 404 경로를 한 번도 지나지 않습니다
    (구현_범위.md 1절의 "고정 계정 둘"이 최소값인 이유).
    """
    return _credentials(OTHER_LOGIN_ID_ENV, OTHER_PASSWORD_ENV)


def _sign_in(base_url: str, login_id: str, password: str) -> httpx.Client:
    """Log in and return a client that carries the session.

    ⚠️ **쿠키 병을 쓰지 않고 `Cookie` 헤더를 직접 답니다.** 세션 쿠키에는 `Secure` 가 붙어
    있는데(ADR-0013), 파이썬의 `http.cookiejar` 는 그런 쿠키를 평문 HTTP 로 **보내지
    않습니다** — 브라우저와 달리 `localhost` 예외가 없습니다. 그대로 두면 로그인은 200 인데
    다음 요청이 401 이고, 증상이 인증 결함처럼 보입니다 (2026-08-19 실측).

    HTTPS 종단이 붙으면(ADR-0016) 이 우회는 불필요해지지만, 그때도 해롭지는 않습니다.
    """
    client = httpx.Client(base_url=base_url, timeout=30.0)
    response = client.post("/v1/auth/login", json={"loginId": login_id, "password": password})
    if response.status_code != 200:
        client.close()
        pytest.fail(f"로그인 실패({login_id}): {response.status_code} {response.text}")

    token = response.cookies.get("session_token")
    if token is None:
        client.close()
        pytest.fail("로그인 응답에 session_token 쿠키가 없습니다")

    client.cookies.clear()
    client.headers["Cookie"] = f"session_token={token}"
    return client


@pytest.fixture(scope="session")
def client(base_url: str):
    """Session-scoped HTTP client.

    The timeout is deliberate and should match your end-to-end latency budget: a hung
    request must fail the test rather than stall the job.

    ⚠️ 인증이 없습니다. 로그인이 필요한 경로에는 `signed_in` 을 쓰세요 — 이 클라이언트가
    401 을 받는 것 자체가 검사 대상인 경우가 있습니다.
    """
    with httpx.Client(base_url=base_url, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="session")
def signed_in(base_url: str, credentials: tuple[str, str]):
    """Logged in as the first account.

    ⚠️ `with` 문을 쓰지 않습니다. `_sign_in` 이 이미 로그인 요청을 보내 클라이언트가 열린
    상태라, 다시 컨텍스트로 열면 httpx 가 `RuntimeError` 를 냅니다 (2026-08-19 실측).
    """
    client = _sign_in(base_url, *credentials)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def other_signed_in(base_url: str, other_credentials: tuple[str, str]):
    """Logged in as the second account — the stranger in INV-9."""
    client = _sign_in(base_url, *other_credentials)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def product_image() -> bytes:
    """A product photo that clears the contract's rules.

    계약은 JPEG / PNG / WebP, 최대 10MB, **짧은 변 512px 이상**을 요구합니다. 파일로 커밋하지
    않고 만들어 쓰는 이유는 둘입니다 - 루트 `.gitignore` 가 화이트리스트 방식이라 새 바이너리는
    조용히 빠질 수 있고(AGENTS.md), 규격이 바뀌면 고쳐야 할 곳이 이 한 줄이기 때문입니다.
    """
    buffer = io.BytesIO()
    Image.new("RGB", (768, 768), (208, 190, 160)).save(buffer, format="PNG")
    return buffer.getvalue()

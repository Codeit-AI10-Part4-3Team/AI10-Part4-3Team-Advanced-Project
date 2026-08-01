"""Shared fixtures for the cross-app E2E harness.

The harness talks to running services over HTTP only — never import `api`,
`backend_core` or `ai_engine` here (app-boundary rule, see e2e/README.md).
"""

import os

import httpx
import pytest

BASE_URL_ENV = "E2E_BASE_URL"


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
def client(base_url: str):
    """Session-scoped HTTP client.

    The timeout is deliberate and should match your end-to-end latency budget: a hung
    request must fail the test rather than stall the job.
    """
    with httpx.Client(base_url=base_url, timeout=30.0) as c:
        yield c

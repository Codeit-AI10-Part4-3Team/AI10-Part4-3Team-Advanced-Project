"""Dependency wiring.

Every collaborator a router uses is resolved through a `Depends(...)` provider so tests
can substitute it via `app.dependency_overrides` — including the AI engine, which must
never be called for real from a test (external calls cost money and make CI
non-deterministic).

Each provider is the named seam where a stub gets replaced by the real thing. Replace a
stub *at* its seam, not around it.
"""

import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, Response

from api.errors import unauthorized
from backend_core import tokens
from backend_core.accounts import Account, find_by_user_id
from backend_core.ai_client import AiEngineClient, HttpAiEngineClient
from backend_core.config import SESSION_COOKIE_NAME, Settings, get_settings
from backend_core.storage import connect


@lru_cache(maxsize=1)
def settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def ai_client() -> AiEngineClient:
    return HttpAiEngineClient(
        settings().ai_engine_url,
        settings().ai_engine_timeout_s,
        settings().brief_fill_timeout_s,
        settings().draft_timeout_s,
        settings().render_timeout_s,
    )


def resolve_ai_client(app: FastAPI) -> AiEngineClient:
    """The engine seam **for callers outside the request cycle** — the render worker.

    ⚠️ Calling `ai_client()` directly from the worker looked equivalent and is not.
    `app.dependency_overrides` is consulted by FastAPI when it resolves a `Depends(...)`,
    and nowhere else — so a worker that called the provider itself got the **real HTTP
    client** even in a test that had substituted a fake, and went out to the network
    (2026-08-14 실측: a job sat `running` for the render timeout while the suite waited on a
    connection to localhost:8100). Test suites must never make external calls (AGENTS.md).

    Reading the overrides here is what keeps one seam rather than two.
    """
    provider = app.dependency_overrides.get(ai_client, ai_client)
    return provider()


def db() -> Iterator[sqlite3.Connection]:
    """One connection per request, closed when the response is done.

    ⚠️ A plain `def`, not `async def`. sqlite3 is blocking, and FastAPI only moves sync
    dependencies to the threadpool — an `async def` here would run the open and every query
    on the event loop, where with a single worker one slow call stalls every other request
    (API_계약.md 2.2절, ADR-0011).
    """
    with connect(settings().db_path) as connection:
        yield connection


def current_user(
    response: Response,
    connection: Annotated[sqlite3.Connection, Depends(db)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Account:
    """The logged-in account, or 401.

    Depend on this from every route the contract protects — everything except `/health` and
    `/v1/auth/*` (API_계약.md 6절).

    Two steps, and the second is not redundant. The token is signed, so its `userId` is
    trustworthy, but "trustworthy" is not "still exists": the account could have been
    dropped from `ADGEN_ACCOUNTS` since the token was issued, and a stateless token cannot
    know that (ADR-0013). Looking the account up is also what lets `GET /v1/me` answer with
    the stored row rather than with whatever the cookie claims.

    ⚠️ Marking the response uncacheable is done **here** rather than per route on purpose.
    Everything behind this dependency is by definition one user's data, and whether it gets
    stored by something in front of us is not a per-route judgement call. A reverse proxy is
    an open decision (API_계약.md 2절, 소관 05), so the header has to already be right when
    one appears — a proxy handing user A's session list to user B is not a bug you find in
    testing. Routes added later inherit this by depending on `current_user`.
    """
    response.headers["Cache-Control"] = "no-store"

    if session_token is None:
        unauthorized()

    user_id = tokens.verify(session_token, settings().session_secret)
    if user_id is None:
        unauthorized()

    account = find_by_user_id(connection, user_id)
    if account is None:
        # Signed, unexpired, and pointing at nobody. Same answer as no cookie at all: the
        # client's move is to log in again either way.
        unauthorized()
    return account

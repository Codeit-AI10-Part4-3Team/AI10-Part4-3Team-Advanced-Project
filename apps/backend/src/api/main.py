"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.

Contract: packages/contracts/openapi.yaml — both the paths served here and the paths this
app calls on apps/ai-engine.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import deps, sweeper, worker
from api.errors import api_error_handler, unhandled_error_handler, validation_error_handler
from api.routes import auth, catalog, jobs, sessions
from backend_core.accounts import count as account_count
from backend_core.accounts import seed
from backend_core.storage import connect, init_schema
from backend_core.tokens import require_secret


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Make the database usable before the first request reaches it.

    The tables are created and the fixed accounts are seeded on every startup. There is no
    separate migration step to hang this off: deployment is `git pull` + `docker compose up`
    (ADR-0011), so anything that must happen before serving has to happen here.

    Seeding runs every time on purpose — it is an upsert that keeps `user_id` (accounts.py),
    which is how a rotated hash in infra/.env reaches the row when there is no
    password-change endpoint (ADR-0008).
    """
    settings = deps.settings()

    with connect(settings.db_path) as connection:
        init_schema(connection)
        seed(connection, settings.accounts)

        # ADR-0013 says a missing signing key must stop the process, not the first login.
        #
        # ⚠️ The condition is **how many accounts are in the database**, not how many are
        # configured, and the difference is the whole point. `ADGEN_ACCOUNTS` says what this
        # startup was told to seed; the file says what is actually there. With a named volume
        # (ADR-0014) they come apart the first time someone restarts without their .env:
        # `seed([])` does not delete anything, so a real account survives, `authenticate`
        # succeeds against it, and `tokens.issue` then raises on the empty key — a 500 on a
        # correct password, which is exactly the failure this check exists to prevent
        # (2026-08-14, PR #84 리뷰에서 신호정 발견).
        #
        # An empty database still starts with no key: a fresh clone has to serve /health,
        # because a stack that needs configuration before it starts cannot be deployed empty
        # (config.py).
        if account_count(connection):
            require_secret(settings.session_secret)

        # ⚠️ Before the worker starts, not after. A job left `running` by a crash or a
        # deploy is a session stuck in `rendering` for ever, because `rendering` has no edge
        # back and nothing would ever pick that job up again (ADR-0015).
        worker.requeue_interrupted(connection)

    # ⚠️ Two background tasks, nested rather than merged. They have nothing to say to each
    # other and different failure modes: a stalled render leaves a spinner, a stalled sweep
    # leaves personal data past its period (세션_보관_정책 2절). Keeping them separate means
    # turning one off for a test does not turn off the other.
    async with (
        worker.lifespan_task(_app, settings.worker_poll_interval_s, settings.worker_enabled),
        sweeper.lifespan_task(settings),
    ):
        yield


# ⚠️ `redirect_slashes=False` is a **security** setting here, not a style choice.
# Starlette's slash redirect builds an *absolute* URL from `scope["scheme"]`, and behind our
# proxy chain that scheme is always `http`: the frontend nginx overwrites `X-Forwarded-Proto`
# with its own (plaintext) `$scheme`, and uvicorn runs without `--proxy-headers` anyway. So
# once TLS terminates at the front proxy (ADR-0016), `POST https://host/v1/auth/login/`
# answers `307 Location: http://host/v1/auth/login` — and 307 preserves method and body, so
# the password goes out in the clear once before the proxy redirects it back to HTTPS. The
# request succeeds, so nothing shows on screen (issue #129).
# Turning the redirect off is safe: no route and no contract path ends in a slash, and the
# router's own 404 already carries the contract error shape (see the handler below).
app = FastAPI(title="adgen-backend", lifespan=lifespan, redirect_slashes=False)

# The contract's error shape is {code, message}; FastAPI's default is {"detail": ...}.
# ⚠️ Register on *Starlette's* HTTPException, not FastAPI's. FastAPI's is a subclass, and
# the 404 for an unmatched route is raised by Starlette's router as the base class — so
# registering the subclass leaves exactly the most common error escaping the contract.
app.add_exception_handler(StarletteHTTPException, api_error_handler)

# ⚠️ The handler above does not cover request validation — FastAPI raises
# `RequestValidationError`, which is not an `HTTPException`. Leaving it out sent the API's
# **most common** error out in FastAPI's own `{"detail": [...]}` shape, with no `code` for a
# client to branch on (2026-08-14 실측).
app.add_exception_handler(RequestValidationError, validation_error_handler)

# ⚠️ And the last resort. `INTERNAL` is in the contract's `ErrorCode`, so a client is told it
# may receive one — but an unhandled exception left as Starlette's plain-text
# `Internal Server Error`, with no JSON at all. The `else` branch in `api_error_handler` was
# written for this and could never run, because that handler is only registered for
# `StarletteHTTPException`.
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(sessions.router)
app.include_router(jobs.router)

# ⚠️ Every router above is behind `current_user`. The template's `/v1/ask` used to sit here
# unauthenticated as a documented exemption; it was deleted once the frontend moved to the
# ad path (API_계약.md 7절). **Do not reintroduce an unauthenticated /v1 route** — the
# contract protects every /v1 path except /health and /v1/auth/* (API_계약.md 6절), and the
# exemption existed only because /v1/ask was not a contract path.


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Does not check the AI engine or any upstream API on purpose: this app must stay up and
    serve the fallback path precisely when its dependencies are down.
    """
    return {"status": "ok"}

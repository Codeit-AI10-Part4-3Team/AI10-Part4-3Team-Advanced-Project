"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.

Contract: packages/contracts/openapi.yaml — both the paths served here and the paths this
app calls on apps/ai-engine.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import deps, worker
from api.errors import api_error_handler
from api.routes import ask, auth, catalog, jobs, sessions
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
        # An empty database still starts with no key: a fresh clone has to serve /health and
        # /v1/ask, because a skeleton that needs configuration before it moves is not a
        # walking skeleton (config.py).
        if account_count(connection):
            require_secret(settings.session_secret)

        # ⚠️ Before the worker starts, not after. A job left `running` by a crash or a
        # deploy is a session stuck in `rendering` for ever, because `rendering` has no edge
        # back and nothing would ever pick that job up again (ADR-0015).
        worker.requeue_interrupted(connection)

    async with worker.lifespan_task(_app, settings.worker_poll_interval_s, settings.worker_enabled):
        yield


app = FastAPI(title="adgen-backend", lifespan=lifespan)

# The contract's error shape is {code, message}; FastAPI's default is {"detail": ...}.
# ⚠️ Register on *Starlette's* HTTPException, not FastAPI's. FastAPI's is a subclass, and
# the 404 for an unmatched route is raised by Starlette's router as the base class — so
# registering the subclass leaves exactly the most common error escaping the contract.
app.add_exception_handler(StarletteHTTPException, api_error_handler)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(sessions.router)
app.include_router(jobs.router)

# ⚠️ `/v1/ask` is the template's question-and-answer path, not part of the ad-generation
# contract, and it is deliberately left unauthenticated. The contract protects "every /v1
# path except /health and /v1/auth/*" (API_계약.md 6절), but that sentence describes the
# contract's own paths — this one is scheduled for replacement, not protection. Reasoning
# and the condition that ends this exemption: API_계약.md 7절.
app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Does not check the AI engine or any upstream API on purpose: this app must stay up and
    serve the fallback path precisely when its dependencies are down.
    """
    return {"status": "ok"}

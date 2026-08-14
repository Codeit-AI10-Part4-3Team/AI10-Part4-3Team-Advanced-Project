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

from api import deps
from api.errors import api_error_handler
from api.routes import ask, auth, catalog, sessions
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

    # ADR-0013 says a missing signing key must stop the process, not the first login. The
    # condition is `accounts` rather than the key alone, because a fresh clone with no .env
    # at all still has to serve /health and /v1/ask — a skeleton that needs configuration
    # before it moves is not a walking skeleton (config.py). Configured accounts are the
    # signal that auth is meant to work here, and a deployment always has them (ADR-0008),
    # so the deployment always fails fast.
    if settings.accounts:
        require_secret(settings.session_secret)

    with connect(settings.db_path) as connection:
        init_schema(connection)
        seed(connection, settings.accounts)

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

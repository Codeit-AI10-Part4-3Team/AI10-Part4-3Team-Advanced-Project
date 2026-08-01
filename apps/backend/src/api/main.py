"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.

Contract: packages/contracts/openapi.yaml — both the paths served here and the paths this
app calls on apps/ai-engine.
"""

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.errors import api_error_handler
from api.routes import ask

app = FastAPI(title="my-ai-project-backend")

# The contract's error shape is {code, message}; FastAPI's default is {"detail": ...}.
# ⚠️ Register on *Starlette's* HTTPException, not FastAPI's. FastAPI's is a subclass, and
# the 404 for an unmatched route is raised by Starlette's router as the base class — so
# registering the subclass leaves exactly the most common error escaping the contract.
app.add_exception_handler(StarletteHTTPException, api_error_handler)

app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Does not check the AI engine or any upstream API on purpose: this app must stay up and
    serve the fallback path precisely when its dependencies are down.
    """
    return {"status": "ok"}

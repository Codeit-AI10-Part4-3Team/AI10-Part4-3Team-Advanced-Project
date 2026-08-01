"""`/v1/ask` — the public entry point of the walking skeleton.

Thin by construction: validate (pydantic does it), call the domain, return. If you find
yourself writing an `if` about business meaning here, it belongs in backend_core.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps import ai_client
from backend_core.ai_client import AiEngineClient
from backend_core.models import Answer, AskRequest
from backend_core.pipeline import answer_question

router = APIRouter(prefix="/v1", tags=["ask"])


@router.post("/ask", response_model=Answer)
def ask(
    request: AskRequest,
    # Annotated[..., Depends(...)] rather than a `= Depends(...)` default: the default
    # form is a function call in a default argument (ruff B008) and hides the type.
    ai: Annotated[AiEngineClient, Depends(ai_client)],
) -> Answer:
    """Answer a question, grounded if possible and falling back if not.

    Always 200 with a usable body — see backend_core.pipeline for why the degraded path
    is a response rather than an error.
    """
    return answer_question(request.question, request.locale, ai)

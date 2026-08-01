"""FastAPI entrypoint for the independently deployable AI engine.

Keep routers thin: request validation -> engine call -> response mapping. Retrieval and
guardrail logic belong in sibling modules of this package, which must stay importable
without FastAPI so the eval harness can call them directly.

⚠️ Retrieval is deliberately **not** an endpoint. It is a stage inside the one-way pipeline
(parsing -> chunking -> embedding -> retrieval -> generation); exposing it would invite
callers into the middle of that pipeline. The eval harness reaches it by importing
`ai_engine.retrieval` directly, which is exactly why that module stays FastAPI-free.

Contract: packages/contracts/openapi.yaml. Only apps/backend calls this service, and it
never calls back — see the app-boundary rule in AGENTS.md.
"""

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from ai_engine.generation import (
    GenerationFailedError,
    Generator,
    StubGenerator,
    generate_answer,
)
from ai_engine.models import GenerateRequest, GenerateResponse
from ai_engine.retrieval import FixtureRetriever, Retriever

app = FastAPI(title="my-ai-project-ai-engine")


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    """Process-wide retriever.

    Cached because reloading the corpus per request would land straight in the caller's
    latency budget. Tests call the generation functions directly with their own retriever
    instead of poking at this cache.
    """
    return FixtureRetriever.from_jsonl()


@lru_cache(maxsize=1)
def get_generator() -> Generator:
    """Process-wide generator. Returns the offline stub until a model client exists."""
    return StubGenerator()


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Deliberately does not touch the corpus or any upstream API: folding dependency health
    into liveness makes an orchestrator restart a process that is perfectly alive.
    """
    return {"status": "ok"}


@app.post("/v1/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    """Write the answer, or refuse with `answer: null`.

    A refusal is a 200 — it means we could have written something and declined to invent
    it. Only an unusable model or vector DB is a 503, which the backend treats exactly like
    a timeout and answers with its own fallback.
    """
    try:
        return generate_answer(request, get_retriever(), get_generator())
    except GenerationFailedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import Response

from ai_engine import brief_fill, draft, render
from ai_engine.config import Settings, get_settings
from ai_engine.generation import (
    GenerationFailedError,
    Generator,
    StubGenerator,
    generate_answer,
)
from ai_engine.models import (
    BriefFillResponse,
    DraftGenerateRequest,
    DraftGenerateResponse,
    Error,
    ImageRenderRequest,
)
from ai_engine.models.legacy_qa import GenerateRequest, GenerateResponse
from ai_engine.retrieval import FixtureRetriever, Retriever
from ai_engine.service_schemas import BriefFillRequest

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Process-wide settings, read once."""
    return get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Announce which branch of every seam is live, loudly.

    ⚠️ 구현_범위 1.1절 requires the running branch to be readable without opening the source.
    A startup line is the one place that is true for every deployment, and the level is
    WARNING on purpose — a stub mistaken for a measurement is how reported numbers become
    fiction.
    """
    mode = settings().generation_mode
    logger.warning(
        "generation seams are running in %r mode (%s)", mode, brief_fill.describe_mode(mode)
    )
    yield


app = FastAPI(title="adgen-ai-engine", lifespan=lifespan)


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


# ---- 광고 생성 (generation 태그) --------------------------------------------------
#
# ⚠️ 인증이 없는 내부 경로입니다. 외부에 열지 않는 것이 이쪽의 방어선이고, 그 방어선은
#    infra/docker-compose.yml 의 `127.0.0.1:8100` 바인딩 하나뿐입니다 - VPC 방화벽은 여러
#    팀이 공유해 우리 통제 밖입니다 (infra/README.md).


UPSTREAM_503: dict[str, Any] = {
    "model": Error,
    "description": "`UPSTREAM_UNAVAILABLE` - 모델을 쓸 수 없습니다. 호출자에게 폴백은 없습니다",
}
"""⚠️ 계약이 생성 경로 셋 모두에 503 을 적고 있으므로 발행 스펙에도 있어야 합니다.

FastAPI 는 `raise HTTPException(503)` 을 스펙에 자동으로 넣지 않습니다. 빼면 계약에는 있고
발행 스펙에는 없는 상태가 되어, 프론트엔드가 계약을 보고 짠 분기가 문서상 근거를 잃습니다.

**값만 공유하고 `503:` 키는 라우트마다 리터럴로 적습니다.** `**` 로 펼치면 정적 분석기가
어느 상태 코드가 문서화됐는지 보지 못해, 문서화가 빠진 라우트를 잡아 주지 못합니다.
"""


@app.post("/v1/brief:fill", responses={503: UPSTREAM_503})
def fill_brief(
    body: Annotated[BriefFillRequest, Form(media_type="multipart/form-data")],
) -> BriefFillResponse:
    """Infer `category` and `target`.

    ⚠️ `media_type` is not decoration: without it the published `/openapi.json` advertises
    `application/x-www-form-urlencoded` for a multipart body, and every test that posts a
    file still passes.

    ⚠️ 503 belongs here even though this is the seam the caller degrades around. The two are
    different things: **degrading** is what the caller does when no response arrives at all
    (outage, 15s timeout), while a 503 is this service saying it cannot serve. The contract
    lists both, so leaving the 503 out would let an unhandled error escape as a 500 and give
    the caller a status it has no branch for.
    """
    try:
        return brief_fill.fill_brief(body, settings())
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/draft:generate", responses={503: UPSTREAM_503})
def generate_draft(request: DraftGenerateRequest) -> DraftGenerateResponse:
    """Write the draft, or refuse without inventing anything.

    A refusal is a 200 with `draft` omitted. Only an unusable model is a 503, and the caller
    has no fallback for it — that is the design, not a gap (ADR-0005).
    """
    try:
        return draft.generate_draft(request, settings())
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/v1/image:render",
    responses={
        200: {"content": {"image/webp": {}}, "description": "이미지 1장 (무손실 WebP)"},
        503: UPSTREAM_503,
    },
    response_class=Response,
)
def render_image(request: ImageRenderRequest) -> Response:
    """Return the finished image as lossless WebP bytes.

    ⚠️ `response_class=Response` and the explicit `responses` entry are both required. Left
    to its default FastAPI documents this as `application/json`, and the published contract
    would claim JSON for a body that is image bytes.

    The caller runs this inside a job, so the request that waits here is the job worker, not
    a user's (API_계약.md 2.1절).
    """
    try:
        payload = render.render_image(request, settings())
    except (NotImplementedError, render.RenderFailedError) as exc:
        # ⚠️ 둘 다 503 입니다. "아직 안 만들었다"와 "지금 못 만든다"는 우리에게는 다른
        # 이야기지만 호출자에게는 같은 답이고, 계약이 이 경로에 준 실패 코드는 하나입니다.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=payload, media_type="image/webp")

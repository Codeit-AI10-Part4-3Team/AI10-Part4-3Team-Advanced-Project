"""HTTP client for apps/ai-engine.

⚠️ This module is the *entire* coupling between the two apps. Never `import ai_engine`
here — a Python import across that line silently destroys the "independently deployable
AI module" property the repo structure exists to prove (AGENTS.md).

The `AiEngineClient` protocol is the seam tests substitute; the real client is only ever
constructed in `api.deps`.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from backend_core.models.generation import (
    BriefFillResponse,
    DraftGenerateRequest,
    DraftGenerateResponse,
)
from backend_core.models.legacy_qa import Answer, Source
from backend_core.models.patch import DraftPatchEngineRequest


class AiEngineUnavailableError(RuntimeError):
    """Engine timed out, refused the connection, or returned 5xx.

    Callers translate this into the fallback path — it is an expected operating mode,
    not a bug, which is why it gets its own type instead of leaking httpx exceptions.

    ⚠️ Only **one** caller has a fallback: `brief:fill` (ADR-0005). Everywhere else this
    becomes a 503 the user sees. Raising it is not the same as recovering from it.
    """


class AiEngineClient(Protocol):
    """Seam between the real HTTP client and the test fake."""

    def generate(self, question: str, locale: str) -> Answer | None: ...

    def fill_brief(
        self, product_name: str, selling_point: str, note: str, image: bytes, filename: str
    ) -> BriefFillResponse: ...

    def generate_draft(self, request: DraftGenerateRequest) -> DraftGenerateResponse: ...

    def patch_draft(self, request: DraftPatchEngineRequest) -> DraftGenerateResponse: ...


class GenerationTimeoutError(RuntimeError):
    """The engine was reachable but did not finish in time.

    ⚠️ Separate from `AiEngineUnavailableError` because the contract answers them with
    different statuses — 504 `GENERATION_TIMEOUT` against 503 `UPSTREAM_UNAVAILABLE`. A
    client retrying a timeout is reasonable; retrying an outage is not, and collapsing the
    two would take that choice away from the screen.
    """


class HttpAiEngineClient:
    """Real client. One call, one timeout, no retries.

    Retrying inside the request path would multiply the tail latency the caller is
    waiting on; the fallback is cheaper and always available.

    ⚠️ **Three timeouts, not one.** They are budgets for different things: the legacy
    question-and-answer path fronts a user's request, `brief:fill` is the one call with a
    fallback behind it (ADR-0005), and draft generation is capped at the 60s the contract
    promises. A single shared value would either cut the draft off early or let the brief
    hold a request open long past the point where degrading is the better answer.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float,
        brief_fill_timeout_s: float,
        draft_timeout_s: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._brief_fill_timeout_s = brief_fill_timeout_s
        self._draft_timeout_s = draft_timeout_s

    def fill_brief(
        self, product_name: str, selling_point: str, note: str, image: bytes, filename: str
    ) -> BriefFillResponse:
        """Ask the engine to infer `category` and `target`.

        ⚠️ Every failure here is `AiEngineUnavailableError`, timeouts included — and that is
        the one place the distinction does *not* matter, because the caller's answer is the
        same either way: skip the auto-fill, stay in `brief_filling`, say `degraded`
        (ADR-0005). The other two seams have no fallback and so keep the two apart.

        The image travels as multipart bytes. Base64 would inflate the body by a third, and
        a path would assume the two apps share a filesystem — they do not, and are not
        allowed to (AGENTS.md 아키텍처 경계).
        """
        try:
            response = httpx.post(
                f"{self._base_url}/v1/brief:fill",
                data={
                    "productName": product_name,
                    "sellingPoint": selling_point,
                    "note": note,
                },
                files={"productImage": (filename, image)},
                timeout=self._brief_fill_timeout_s,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AiEngineUnavailableError(str(exc)) from exc
        return BriefFillResponse.model_validate(response.json())

    def generate_draft(self, request: DraftGenerateRequest) -> DraftGenerateResponse:
        """Ask the engine to write the draft.

        ⚠️ A response with no `draft` is a **successful** call — the engine could have
        written something and declined to invent it. That is a 422 to the user, decided by
        the route, not an error here.
        """
        try:
            response = httpx.post(
                f"{self._base_url}/v1/draft:generate",
                json=request.model_dump(by_alias=True, exclude_none=True),
                timeout=self._draft_timeout_s,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise GenerationTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AiEngineUnavailableError(str(exc)) from exc
        return DraftGenerateResponse.model_validate(response.json())

    def patch_draft(self, request: DraftPatchEngineRequest) -> DraftGenerateResponse:
        """Change the named parts of an existing draft.

        ⚠️ `exclude_unset` on the patch, not `exclude_none`. In this one family an omitted
        key and `""` are opposite instructions — "leave it alone" against "empty it" — and
        `exclude_none` would collapse them (models/patch.py).
        """
        payload = request.model_dump(by_alias=True, exclude_none=True)
        payload["patch"] = request.patch.model_dump(by_alias=True, exclude_unset=True)
        try:
            response = httpx.post(
                f"{self._base_url}/v1/draft:patch", json=payload, timeout=self._draft_timeout_s
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise GenerationTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AiEngineUnavailableError(str(exc)) from exc
        return DraftGenerateResponse.model_validate(response.json())

    def generate(self, question: str, locale: str) -> Answer | None:
        """Return the grounded answer, or None when the engine honestly refused.

        Raises AiEngineUnavailableError for transport failures and 5xx. The distinction
        matters: a refusal means "we could have written something and declined to invent
        it", an outage means "we never got to ask".
        """
        payload = {"question": question, "locale": locale}
        try:
            response = httpx.post(
                f"{self._base_url}/v1/generate", json=payload, timeout=self._timeout_s
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AiEngineUnavailableError(str(exc)) from exc

        body = response.json()
        if body.get("answer") is None:
            return None
        return Answer(
            text=body["answer"],
            message_mode="grounded",
            sources=[Source.model_validate(s) for s in body.get("sources", [])],
        )

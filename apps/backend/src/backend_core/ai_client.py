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
    ImageRenderRequest,
)
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

    def fill_brief(
        self, product_name: str, selling_point: str, note: str, image: bytes, filename: str
    ) -> BriefFillResponse: ...

    def generate_draft(self, request: DraftGenerateRequest) -> DraftGenerateResponse: ...

    def patch_draft(self, request: DraftPatchEngineRequest) -> DraftGenerateResponse: ...

    def render_image(self, request: ImageRenderRequest) -> bytes: ...


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

    ⚠️ **Four timeouts, not one.** They are budgets for different things, and three of them
    front a user's request while the fourth does not:

    - the legacy question-and-answer path — a user is waiting;
    - `brief:fill` — a user is waiting, and this is the one call with a fallback behind it
      (ADR-0005), so overrunning is cheap;
    - draft generation — a user is waiting, capped at the 60s the contract promises;
    - `image:render` — **the job worker is waiting, not a user** (ADR-0015), which is the
      only reason minutes are acceptable.

    A single shared value would either cut the render off long before it could finish or let
    a user's request hang for minutes. The two cannot be the same number.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float,
        brief_fill_timeout_s: float,
        draft_timeout_s: float,
        render_timeout_s: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._brief_fill_timeout_s = brief_fill_timeout_s
        self._draft_timeout_s = draft_timeout_s
        self._render_timeout_s = render_timeout_s

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

        ⚠️ `/v1/draft:patch` on apps/ai-engine landed 2026-08-15. Until then the contract
        described it and this client called it, so every `PATCH .../draft` against the real
        engine came back 404 — and a 404 is mapped below like any other HTTP error, so the
        user was told `503 UPSTREAM_UNAVAILABLE` and whoever debugged it went looking at a
        service that was running fine. Kept as a note because the mapping is unchanged: any
        future missing route on the engine fails exactly this way.

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

    def render_image(self, request: ImageRenderRequest) -> bytes:
        """Draw the picture. Returns lossless WebP bytes, not JSON.

        ⚠️ **The request that waits here is the job worker's, never a user's** (API_계약.md
        2.1절). Minutes are acceptable precisely because nobody is holding a connection open
        — which is why this is the one call with a timeout measured in minutes rather than
        seconds, and why putting it back on a request path would undo the whole reason
        `finalize` returns 202.
        """
        try:
            response = httpx.post(
                f"{self._base_url}/v1/image:render",
                json=request.model_dump(by_alias=True, exclude_none=True),
                timeout=self._render_timeout_s,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise GenerationTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AiEngineUnavailableError(str(exc)) from exc
        return response.content

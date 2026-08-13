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

from backend_core.models.legacy_qa import Answer, Source


class AiEngineUnavailableError(RuntimeError):
    """Engine timed out, refused the connection, or returned 5xx.

    Callers translate this into the fallback path — it is an expected operating mode,
    not a bug, which is why it gets its own type instead of leaking httpx exceptions.
    """


class AiEngineClient(Protocol):
    """Seam between the real HTTP client and the test fake."""

    def generate(self, question: str, locale: str) -> Answer | None: ...


class HttpAiEngineClient:
    """Real client. One call, one timeout, no retries.

    Retrying inside the request path would multiply the tail latency the caller is
    waiting on; the fallback is cheaper and always available.
    """

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

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

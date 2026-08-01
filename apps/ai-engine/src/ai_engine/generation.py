"""Generation stage: retrieved passages -> a grounded answer, or an honest refusal.

The `Generator` protocol is the seam where `StubGenerator` is replaced by a real model
client (HyperCLOVA X, OpenAI, a local model). Keeping the swap behind one protocol is what
stops model-client details from leaking into the routers or the eval harness.

⚠️ Every path through this module runs `guardrail.verify`. Do not add one that skips it —
the on/off delta is a reported metric, and a bypassed guardrail invalidates it rather than
fixing whatever it was blocking.
"""

from __future__ import annotations

from typing import Protocol

from ai_engine import guardrail
from ai_engine.models import GenerateRequest, GenerateResponse, Passage, Source
from ai_engine.retrieval import Retriever

TOP_K = 3


class GenerationFailedError(RuntimeError):
    """The model client is unusable (auth, quota, outage).

    Distinct from a refusal: a refusal is a 200 with `answer: null`, this is a 503 the
    caller treats exactly like a timeout.
    """


class Generator(Protocol):
    """Seam between the offline stub and a real model client."""

    def complete(self, prompt: str) -> str: ...


class StubGenerator:
    """Offline stand-in: echoes the evidence block back as a short answer.

    It exists so the vertical slice runs with no API key and no network. It is *not* a
    model — the text it returns is source text, which is why it trivially passes the
    guardrail. Replace it before reporting any generation-quality number.
    """

    def complete(self, prompt: str) -> str:
        evidence = _evidence_lines(prompt)
        if not evidence:
            return guardrail.NO_EVIDENCE_SENTINEL
        return " ".join(evidence[:2])


def _evidence_lines(prompt: str) -> list[str]:
    """Pull the `- (title) text` lines out of the rendered prompt's <근거> block."""
    lines: list[str] = []
    inside = False
    for raw in prompt.splitlines():
        if raw.startswith("<근거>"):
            inside = True
            continue
        if raw.startswith("</근거>"):
            break
        if inside and raw.startswith("- ("):
            lines.append(raw.split(") ", 1)[-1])
    return lines


def generate_answer(
    request: GenerateRequest,
    retriever: Retriever,
    generator: Generator,
    *,
    guardrail_enabled: bool = True,
) -> GenerateResponse:
    """Retrieve, generate, verify — and refuse rather than invent.

    `guardrail_enabled=False` exists only for the eval harness's control run. The response
    reports which mode produced it (`guardrailApplied`) so a control-run output can never
    be mistaken for a verified one.
    """
    passages: list[Passage] = retriever.search(request.question, top_k=TOP_K)
    if not passages:
        return GenerateResponse(
            answer=None,
            sources=[],
            refusal_reason="no_evidence",
            guardrail_applied=guardrail_enabled,
        )

    prompt = guardrail.build_prompt(request.question, passages)
    try:
        body = generator.complete(prompt)
    except GenerationFailedError:
        raise
    except Exception as exc:  # model clients raise their own zoo of exceptions
        raise GenerationFailedError(str(exc)) from exc

    ctx = guardrail.GuardrailContext.from_passages(passages)
    report = guardrail.verify(body, ctx, enabled=guardrail_enabled)
    sources = [Source(title=p.title, quote=p.text, url=p.url) for p in passages]

    # With the guardrail off nothing is blocked — that is the control condition, and the
    # response says so rather than pretending the text was verified.
    if guardrail_enabled and not report.passed:
        return GenerateResponse(
            answer=None, sources=sources, refusal_reason="guardrail", guardrail_applied=True
        )

    return GenerateResponse(
        answer=body.strip(),
        sources=sources,
        refusal_reason=None,
        guardrail_applied=guardrail_enabled,
    )

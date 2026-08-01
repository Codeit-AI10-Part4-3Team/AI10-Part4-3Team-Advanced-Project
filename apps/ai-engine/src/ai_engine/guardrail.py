"""Guardrail v0 — force evidence, refuse without it.

Two halves, and both are needed:

1. **Prompt-side** (`GUARDRAIL_PROMPT_V0`, `build_prompt`) — tells the model to write only
   from retrieved source text. Necessary, insufficient: a prompt is a request, not a
   guarantee.
2. **Output-side** (`verify`) — checks the produced text against the retrieved passages
   after the fact. This is what makes hallucination suppression *measurable* rather than
   assumed.

⚠️ The on/off switch exists solely so the same eval set can be scored in both modes
(guardrail off = control group). Turning it off to make a test or a demo pass does not fix
anything — it invalidates the metric the report rests on.

Design note: `verify` is intentionally lexical and dependency-free. A model-graded check
would be stronger but costs an external call per request and makes CI non-deterministic;
that belongs in the eval harness's cross-model grading step (grading model ≠ generation
model).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_engine.models import GuardrailReport, Passage, Source, Violation

GUARDRAIL_PROMPT_V0 = """당신은 아래 <근거>만 사용해 답변하는 작성자입니다.

[절대 규칙]
1. <근거>에 있는 내용만 사용하세요. 그 밖의 지식·상식·추측을 쓰지 마세요.
2. 근거에 없는 수치, 날짜, 기관명, 고유명사를 만들어 내지 마세요.
3. 문장은 3개 이하로 짧게 쓰고, 전문 용어 대신 쉬운 말을 쓰세요.
4. <근거>가 비어 있으면 답을 만들지 말고 정확히 `NO_EVIDENCE` 한 단어만 출력하세요.

[질문]
{question}

<근거>
{evidence}
</근거>

위 규칙을 지켜 답변 본문만 출력하세요. 설명이나 머리말을 붙이지 마세요."""

NO_EVIDENCE_SENTINEL = "NO_EVIDENCE"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")

# Below this share of overlapping character bigrams, a sentence is treated as saying
# something the sources do not. Tuned against the fixture corpus — re-tune when the real
# corpus lands and record the number in the eval harness, not in someone's head.
SUPPORT_THRESHOLD = 0.5


@dataclass(frozen=True)
class GuardrailContext:
    """What the output is allowed to be built from.

    `allowed_phrases` is the reviewed message frame — fixed scaffolding plus values the
    caller supplied. Declaring it explicitly keeps the check honest: everything outside
    the frame must trace back to a source, and widening the frame is a visible diff rather
    than a silently looser guardrail.
    """

    sources: list[Source]
    allowed_phrases: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_passages(
        cls, passages: list[Passage], allowed_phrases: tuple[str, ...] = ()
    ) -> GuardrailContext:
        sources = [Source(title=p.title, quote=p.text, url=p.url) for p in passages]
        return cls(sources=sources, allowed_phrases=allowed_phrases)


def build_prompt(question: str, passages: list[Passage]) -> str:
    """Render the guardrail prompt. Empty evidence is passed through, not hidden.

    Sending an empty <근거> block is deliberate: rule 4 makes the model answer with the
    NO_EVIDENCE sentinel, so refusal is exercised on the same path as generation instead
    of being a branch the model never sees.
    """
    evidence = "\n".join(f"- ({p.title}) {p.text}" for p in passages)
    return GUARDRAIL_PROMPT_V0.format(question=question, evidence=evidence)


def _bigrams(text: str) -> set[str]:
    compact = _NON_WORD.sub("", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _supported(sentence: str, allowed: set[str]) -> bool:
    grams = _bigrams(sentence)
    if not grams:
        return True  # punctuation-only fragment carries no claim
    return len(grams & allowed) / len(grams) >= SUPPORT_THRESHOLD


def verify(body: str, ctx: GuardrailContext, *, enabled: bool = True) -> GuardrailReport:
    """Check generated text against the evidence it was supposed to come from.

    Returns a report instead of raising: the caller decides what to do with a violation,
    and the eval harness needs the violation list even for outputs that were sent.
    """
    if not enabled:
        # `passed=False` — see GuardrailReport: a disabled guardrail is not a pass.
        return GuardrailReport(enabled=False, passed=False, violations=[])

    violations: list[Violation] = []
    stripped = body.strip()

    if not stripped or stripped == NO_EVIDENCE_SENTINEL:
        violations.append("empty_output")
    if not ctx.sources:
        violations.append("no_evidence")

    if stripped and stripped != NO_EVIDENCE_SENTINEL:
        allowed: set[str] = set()
        for source in ctx.sources:
            allowed |= _bigrams(source.quote)
        for phrase in ctx.allowed_phrases:
            allowed |= _bigrams(phrase)

        sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
        if any(not _supported(sentence, allowed) for sentence in sentences):
            violations.append("unsupported_claim")

    return GuardrailReport(enabled=True, passed=not violations, violations=violations)

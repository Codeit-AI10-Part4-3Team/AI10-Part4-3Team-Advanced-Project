"""Guardrail — force evidence, refuse without it.

⚠️ **두 벌이 들어 있고, 서로 다른 경로의 것입니다.** 아래쪽 `verify` 계열은 템플릿 질의응답
(`/v1/generate`)의 것이고, `check_claims` 계열이 광고 경로의 것입니다. 판정 방식이 다른
이유는 [ADR-0019](../../../../docs/adr/0019-광고_카피_가드레일은_금지_표현을_검출한다.md)에
있습니다 - 한 줄로 줄이면 **근거가 한 문장뿐인 짧은 카피에서는 어휘 겹침이 판정 근거가 되지
못하기 때문**입니다.

질의응답 경로가 삭제되면 `verify` 와 `GuardrailContext` 도 함께 나갑니다 (AGENTS.md 현재 상태).
그때까지 **둘을 섞지 마세요** - 광고 경로에서 `verify` 를 부르면 지시문(`visualPlan`)이 전부
위반으로 잡히고, 정작 타사 비교는 통과합니다 (2026-08-20 실측).

--- 질의응답 경로 (삭제 예정) ---------------------------------------------------------

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
from typing import Literal

from ai_engine.models.legacy_qa import GuardrailReport, Passage, Source, Violation

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


# --- 광고 경로 (ADR-0019) --------------------------------------------------------------


ClaimKind = Literal["number", "comparison", "superlative", "award"]
"""검출하는 금지 표현의 갈래. 생성_파이프라인 5.1 이 열거한 항목에서 왔습니다.

⚠️ **효능과 성분은 여기 없고, 그것은 누락이 아니라 한계입니다.** 어떤 낱말이 효능 주장인지는
사전 없이 판정할 수 없고, 사전을 지어내면 그 사전이 곧 근거 없는 정본이 됩니다. 프롬프트 쪽
금지 사항(`draft_prompt.GUARDRAIL_BLOCK`)은 여전히 둘을 막고 있으므로 **가드레일이 놓치는
것이지 허용하는 것이 아닙니다.** 사람 리뷰와 eval 하네스가 그 구간을 봅니다.
"""


@dataclass(frozen=True)
class ClaimReport:
    """광고 카피 한 벌에 대한 판정.

    ⚠️ `enabled=False` 는 **통과가 아닙니다** (`passed` 도 `False`). 대조군 실행과 검증을
    통과한 출력이 같은 값으로 보이면 환각 억제율의 분자와 분모가 섞입니다 - `GuardrailReport`
    가 같은 이유로 같은 규약을 씁니다.
    """

    enabled: bool
    passed: bool
    violations: tuple[tuple[ClaimKind, str], ...] = ()
    """(갈래, 걸린 표현). 표현을 함께 남기는 이유는 **재생성 프롬프트가 그것을 지목해야**
    하기 때문입니다 (생성_파이프라인 5.1.1절). "위반했다"만 알려 주면 모델이 같은 문장을 다시
    씁니다."""


_CLAIM_PATTERNS: tuple[tuple[ClaimKind, re.Pattern[str]], ...] = (
    # 숫자 자체가 아니라 **단위가 붙은 숫자**를 봅니다. 맨 숫자는 "3중 구조" 처럼 제품명에서
    # 오는 경우가 많고, 광고 주장이 되는 것은 크기를 주장할 때입니다.
    # ⚠️ `위` 와 `등` 은 일부러 뺐습니다. "1위" 는 순위 주장이라 superlative 가, "1등" 은
    # award 가 잡습니다 - 여기 두면 같은 문구가 두 갈래로 세어져 위반 건수가 부풀고, 그
    # 건수가 곧 보고 지표의 분자입니다.
    (
        "number",
        re.compile(
            r"\d+(?:[.,]\d+)?\s*"
            r"(?:%|퍼센트|배|겹|장|매|초|분|시간|일|주일|주|개월|년|ml|mL|L|g|kg|mg|mm|cm|종)"
        ),
    ),
    # 비교는 **대상이 명시된 것만** 잡습니다. 맨 비교급("더 부드러운")까지 잡으면 광고 문구가
    # 거의 다 걸려 판정이 무의미해집니다.
    (
        "comparison",
        re.compile(r"타사|경쟁사|경쟁\s*제품|기존\s*제품|다른\s*제품|일반\s*제품|시중\s*제품|대비"),
    ),
    (
        "superlative",
        re.compile(r"최고|최강|최초|최상|최적|유일|독보적|1\s*위|넘버\s*원|No\.?\s*1|가장"),
    ),
    ("award", re.compile(r"수상|인증|공인|특허|선정|1\s*등|일등")),
)
"""갈래별 검출 패턴. **순수 함수로 유지합니다** - I/O 도 모델 호출도 없습니다 (AGENTS.md).

⚠️ 패턴을 느슨하게 고쳐 테스트를 통과시키지 마세요. 여기서 잡히는 건수가 곧 보고 지표의
분자입니다 - 규칙을 깎으면 억제율이 오르는데, 오른 것은 품질이 아니라 눈감은 양입니다.
"""


def _normalised(text: str) -> str:
    """공백과 문장부호를 지운 비교용 문자열.

    근거에 `"두께 2배"` 라고 적혀 있고 카피가 `"2 배"` 라고 쓰는 경우를 같은 것으로 봐야
    합니다. 붙여 놓고 비교하면 띄어쓰기 차이로 근거를 못 찾는 일이 없습니다.
    """
    return _NON_WORD.sub("", text)


def check_claims(texts: list[str], evidence: str, *, enabled: bool = True) -> ClaimReport:
    """이미지에 그려질 문구가 근거 밖 주장을 담고 있는지 봅니다.

    `texts` 는 **카피와 만화 대사뿐**입니다. `adPlan` 과 `visualPlan` 은 넣지 마세요 - 그것은
    소비자에게 하는 주장이 아니라 제작 지시문이고, 근거와 어휘가 겹칠 이유가 없어 넣는 순간
    전량 위반으로 잡힙니다 (2026-08-20 실측, ADR-0019).

    `evidence` 는 `sellingPoint` + `note` 에 **제품명을 더한** 문자열입니다. 제품명이 들어가는
    것은 근거의 범위를 넓히려는 게 아니라 **사용자가 직접 친 글자를 우리가 지어낸 것으로 세지
    않기 위해서**입니다 (제품명이 `"3겹 물티슈"` 인데 카피가 `3겹` 이라고 쓰면 그것은 우리가
    만든 수치가 아닙니다). 제품명은 효능을 실어 올 수 없으므로 근거의 성격은 그대로입니다
    (생성_파이프라인 5.2절).

    ⚠️ 거절이 아니라 **보고서를 돌려줍니다.** 재생성할지 거절할지는 호출부가 정하고, eval
    하네스는 내보낸 출력의 위반 목록까지 필요합니다 (`verify` 와 같은 규약).
    """
    if not enabled:
        # `passed=False` — 대조군은 통과가 아닙니다. `ClaimReport` 의 주의 참고.
        return ClaimReport(enabled=False, passed=False)

    allowed = _normalised(evidence)
    violations: list[tuple[ClaimKind, str]] = []
    for text in texts:
        for kind, pattern in _CLAIM_PATTERNS:
            for found in pattern.findall(text):
                if _normalised(found) and _normalised(found) in allowed:
                    continue  # 근거에 그대로 있는 표현입니다. 지어낸 것이 아닙니다.
                violations.append((kind, found))

    return ClaimReport(enabled=True, passed=not violations, violations=tuple(violations))

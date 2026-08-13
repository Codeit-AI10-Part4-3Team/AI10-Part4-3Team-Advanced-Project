"""Guardrail behaviour — the part that makes hallucination suppression measurable.

⚠️ If a test here starts failing, the fix is to change the generator or the corpus, never
to loosen `SUPPORT_THRESHOLD` until it passes. The threshold is a measurement parameter.
"""

from ai_engine.guardrail import GuardrailContext, verify
from ai_engine.models.legacy_qa import Passage

PASSAGE = Passage(
    id="p1",
    title="[더미] 안내",
    text="환불은 결제일로부터 7일 이내에 고객센터로 신청하면 처리됩니다.",
)


def context() -> GuardrailContext:
    return GuardrailContext.from_passages([PASSAGE])


def test_text_quoting_the_source_passes() -> None:
    report = verify("환불은 결제일로부터 7일 이내에 고객센터로 신청하면 처리됩니다.", context())
    assert report.passed
    assert report.violations == []


def test_invented_claim_is_caught() -> None:
    """The sentence is plausible and entirely absent from the sources — the target case."""
    report = verify("환불 수수료는 5000원이며 매장에서 현금으로 돌려받습니다.", context())
    assert not report.passed
    assert "unsupported_claim" in report.violations


def test_no_evidence_is_a_violation() -> None:
    report = verify("아무 말이나 씁니다.", GuardrailContext(sources=[]))
    assert not report.passed
    assert "no_evidence" in report.violations


def test_disabled_guardrail_does_not_report_a_pass() -> None:
    """Control-group runs must stay distinguishable from verified ones."""
    report = verify("무엇이든", context(), enabled=False)
    assert report.enabled is False
    assert report.passed is False

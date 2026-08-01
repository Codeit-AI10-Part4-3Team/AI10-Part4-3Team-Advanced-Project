"""Unit tests for the metric functions themselves.

Yes, the measuring instrument gets tested. A silently wrong metric produces a number that
looks fine in a report and cannot be reproduced later.
"""

from metrics import hallucination_rate, percentile, source_fidelity, suppression_rate

SOURCE = "환불은 결제일로부터 7일 이내에 고객센터로 신청하면 처리됩니다."


def test_quoted_text_scores_high() -> None:
    assert source_fidelity(SOURCE, [SOURCE]) == 1.0


def test_invented_text_scores_low() -> None:
    assert source_fidelity("수수료는 5천원이고 매장에서 현금으로 받습니다.", [SOURCE]) < 0.5


def test_empty_prediction_is_zero_not_perfect() -> None:
    """An empty answer trivially contains no unsupported claim — that is not fidelity."""
    assert source_fidelity("", [SOURCE]) == 0.0


def test_hallucination_rate_counts_failures() -> None:
    assert hallucination_rate([True, True, False, False]) == 0.5


def test_suppression_rate_is_relative_reduction() -> None:
    off = [False, False, False, True]  # 75% hallucinated
    on = [True, True, True, False]  # 25% hallucinated
    assert suppression_rate(off, on) == round((0.75 - 0.25) / 0.75, 4)


def test_nothing_to_suppress_reports_zero() -> None:
    """Reporting 100% suppression when the control run was already clean would be a lie."""
    assert suppression_rate([True, True], [True, True]) == 0.0


def test_percentile_picks_the_tail() -> None:
    assert percentile([1.0, 2.0, 3.0, 100.0], 95) == 100.0

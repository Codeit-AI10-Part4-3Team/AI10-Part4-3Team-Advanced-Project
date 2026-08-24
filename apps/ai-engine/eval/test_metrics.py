"""Unit tests for the metric functions themselves.

Yes, the measuring instrument gets tested. A silently wrong metric produces a number that
looks fine in a report and cannot be reproduced later.
"""

import pytest
from metrics import (
    claim_support_rate,
    cosine_similarity,
    degraded_rate,
    hallucination_rate,
    percentile,
    source_fidelity,
    suppression_rate,
    violation_count,
)

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


# ---- 개발자_가이드 4절 지표 표 -----------------------------------------------------------


def test_violation_count_carries_the_sample_size() -> None:
    """⚠️ 표본 없이 적힌 "위반 0건" 은 표본이 붙은 같은 문장보다 강하게 읽힙니다.
    두 값이 한 몸이라는 것을 타입으로 고정합니다 (생성_파이프라인 5.3절)."""
    counted = violation_count([True, True, False])

    assert counted.sample == 3
    assert counted.violations == 1
    assert str(counted) == "3건 중 1건"


def test_a_clean_run_still_reports_its_sample() -> None:
    """D2 가 실제로 마주친 자리입니다 - 위반 0건인데 표본을 빠뜨리면 "위반율 0" 으로 읽힙니다."""
    assert violation_count([True] * 30) == (30, 0)


def test_claim_support_rate_counts_claims_not_rounds() -> None:
    """주장 넷 중 셋이 옳은 카피와 전부 틀린 카피가 같은 값이 되면 안 됩니다."""
    assert claim_support_rate([True, True, True, False]) == 0.75


def test_a_copy_without_claims_is_out_of_scope_not_zero() -> None:
    """⚠️ 0.0 을 주면 "아무 주장도 안 한 카피" 가 최악 점수로 잡혀 평균을 끌어내립니다."""
    with pytest.raises(ValueError):
        claim_support_rate([])


def test_degraded_rate_counts_sessions() -> None:
    assert degraded_rate(["normal", "degraded", "normal", "normal"]) == 0.25


def test_no_sessions_is_zero_not_a_crash() -> None:
    assert degraded_rate([]) == 0.0


def test_cosine_similarity_of_the_same_vector_is_one() -> None:
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_orthogonal_vectors_score_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_a_zero_vector_is_not_a_perfect_match() -> None:
    """영벡터는 방향이 없습니다. 1.0 으로 주면 임베딩이 비어 있을 때 "완벽히 같다" 가 됩니다."""
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_mismatched_dimensions_raise() -> None:
    """차원이 다른 임베딩을 말없이 채점하면 모델을 바꾼 사고가 숫자로 드러나지 않습니다."""
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])

"""채점 러너의 순수 부분(`score`) 단위 테스트.

⚠️ 이 파일이 `test_` 로 시작해도 되는 이유는 `score` 가 순수 함수이기 때문입니다 - 기록
리스트를 받아 지표 딕셔너리를 돌려줄 뿐이고 모델도 네트워크도 부르지 않습니다. 외부 호출이
붙는 자리는 수집 쪽이고 그것은 `run_metrics.py` 밖입니다 (eval/README.md).
"""

from typing import Any

from run_metrics import score


def test_ungraded_rounds_are_not_counted_as_claimless() -> None:
    """⚠️ "아직 채점 안 함" 이 "주장을 안 한 카피" 로 읽히면 안 됩니다.

    빈 배열은 채점 결과이고 필드 없음은 미채점입니다. 한 칸에 묶으면 재지 않은 것이 재서
    그랬던 것으로 읽히며, 그 구별이 이 하네스의 요점입니다.
    """
    rows: list[dict[str, Any]] = [
        {"claimsSupported": [True, False]},
        {"claimsSupported": []},
        {},
    ]

    scored = score(rows)["카피 사실 일치율"]

    assert scored["회차"] == 1
    assert scored["주장"] == 2
    assert scored["주장 없는 회차"] == 1
    assert scored["미채점 회차"] == 1


def test_a_fully_ungraded_run_has_no_rate_at_all() -> None:
    """전량 미채점이면 지표가 통째로 빠집니다(`main` 이 "측정 안 함" 으로 냅니다).

    위 항목이 부분 채점 회차에서만 드러나는 이유입니다.
    """
    rows: list[dict[str, Any]] = [{"latencySeconds": 1.0}, {}]

    assert "카피 사실 일치율" not in score(rows)

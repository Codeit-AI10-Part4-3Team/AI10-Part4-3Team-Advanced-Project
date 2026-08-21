"""Guardrail behaviour — the part that makes hallucination suppression measurable.

⚠️ 패턴을 느슨하게 고쳐 테스트를 통과시키지 마세요. 여기서 잡히는 건수가 곧 보고 지표의
분자입니다 - 규칙을 깎으면 억제율이 오르는데, 오른 것은 품질이 아니라 눈감은 양입니다.

⚠️ 질의응답용 `verify` 계열 테스트 넷은 2026-08-20 에 그 경로와 함께 삭제됐습니다.
"""

import pytest

from ai_engine.guardrail import check_claims

# ---- 광고 경로: 금지 표현 검사 (ADR-0019) -----------------------------------------------

EVIDENCE = "무향 무알코올, 두꺼운 원단 순한 대나무 물티슈"
"""`sellingPoint` + `note` + 제품명. `draft._evidence` 가 만드는 것과 같은 모양입니다."""


@pytest.mark.parametrize(
    "copy",
    [
        "무향·무알코올, 두꺼운 원단의 순한 대나무 물티슈",
        "순한 대나무 물티슈, 무향·무알코올·두꺼운 원단",
        "오늘도 순하게, 대나무 물티슈",
        "이거면 아침이 편해져요",
    ],
    ids=["실물 생성 카피", "부분 교체 후 카피", "평범한 카피", "만화 대사"],
)
def test_copy_that_stays_inside_the_evidence_passes(copy: str) -> None:
    """⚠️ 거짓 양성이 나면 전량 거절이 되어 서비스가 아무것도 못 내보냅니다. 통과 사례를
    먼저 고정하는 이유입니다 - 위반 검출만 검사하면 "전부 위반" 이라고 답해도 통과합니다."""
    assert check_claims([copy], EVIDENCE).passed


@pytest.mark.parametrize(
    ("copy", "kind"),
    [
        ("타사보다 2배 두꺼운 원단", "comparison"),
        ("99.9% 살균, 두꺼운 원단", "number"),
        ("2025 소비자대상 수상", "award"),
        ("가장 순한 대나무 물티슈", "superlative"),
        ("피부과 인증 완료", "award"),
        ("기존 제품 대비 부드럽습니다", "comparison"),
    ],
    ids=["타사 비교", "지어낸 수치", "수상 이력", "최상급", "인증", "기존 제품 비교"],
)
def test_a_claim_the_evidence_does_not_carry_is_caught(copy: str, kind: str) -> None:
    """표시광고법상 허위 과장 광고가 되는 갈래들입니다 (생성_파이프라인 5.1절)."""
    report = check_claims([copy], EVIDENCE)

    assert not report.passed
    assert kind in [found_kind for found_kind, _ in report.violations]


def test_a_number_the_evidence_carries_is_not_a_violation() -> None:
    """⚠️ 근거에 있는 수치를 되풀이하는 것은 지어낸 것이 아닙니다. 이것까지 잡으면 사용자가
    직접 쓴 소구점을 광고에 쓸 수 없게 됩니다."""
    assert check_claims(["3겹 원단으로 든든하게"], "3겹 원단, 두툼합니다").passed


def test_a_number_the_evidence_does_not_carry_is_a_violation() -> None:
    """같은 단위라도 값이 다르면 우리가 만든 수치입니다."""
    report = check_claims(["5겹 원단으로 든든하게"], "3겹 원단, 두툼합니다")

    assert not report.passed
    assert report.violations == (("number", "5겹"),)


def test_spacing_does_not_hide_the_evidence() -> None:
    """근거가 `2배` 라고 적고 카피가 `2 배` 라고 써도 같은 것으로 봅니다."""
    assert check_claims(["두께가 2 배"], "두께 2배 원단").passed


def test_the_violation_carries_the_matched_text() -> None:
    """⚠️ 재생성 프롬프트가 걸린 표현을 지목해야 합니다 (생성_파이프라인 5.1.1절).
    "위반했다" 만 알려 주면 모델이 같은 문장을 다시 씁니다."""
    report = check_claims(["타사보다 2배 두꺼운 원단"], EVIDENCE)

    assert ("comparison", "타사") in report.violations
    assert ("number", "2배") in report.violations


def test_every_text_is_checked_not_just_the_first() -> None:
    """만화형은 여섯 칸이 한 번에 들어옵니다. 첫 칸만 보면 나머지 다섯이 무검사입니다."""
    report = check_claims(["평범한 대사", "괜찮은 대사", "타사보다 좋아요"], EVIDENCE)

    assert not report.passed


def test_a_disabled_guardrail_is_not_a_pass() -> None:
    """⚠️ 대조군 실행과 검증을 통과한 출력이 같은 값으로 보이면 환각 억제율의 분자와 분모가
    섞입니다."""
    report = check_claims(["타사보다 2배 두꺼운 원단"], EVIDENCE, enabled=False)

    assert report.enabled is False
    assert report.passed is False
    assert report.violations == ()

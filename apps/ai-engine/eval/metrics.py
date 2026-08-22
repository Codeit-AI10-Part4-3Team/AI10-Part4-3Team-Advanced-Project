"""Metric functions — pure, so they can be re-run on any prediction set.

Rule: `(prediction, truth) -> score`. No I/O, no model calls, no globals. That is what
makes a reported number reproducible by someone who only has this file and the goldens.

⚠️ Naming matters here. This directory is collected by pytest (`testpaths = ["tests",
"eval"]`), so anything named `test_*.py` runs in CI. The actual scoring run — which calls
a model and costs money — must be named `run_*.py` instead.
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


def _bigrams(text: str) -> set[str]:
    compact = _NON_WORD.sub("", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def source_fidelity(prediction: str, sources: list[str]) -> float:
    """Share of the prediction's bigrams that appear in its cited sources.

    A crude, deterministic stand-in for "did the answer stay inside its evidence". Pair it
    with a cross-model LLM grading pass — and use a grading model *different* from the
    generation model, or the score measures self-agreement rather than fidelity.

    ⚠️ **광고 카피에는 쓰지 마세요. 특히 이 값을 "카피 사실 일치율" 로 보고하면 안 됩니다**
    (개발자_가이드 4절의 지표 표). 어휘 겹침은 근거가 길고 답변이 그것을 풀어 쓰는 질의응답의
    전제 위에 서 있는데, 광고는 근거가 한 문장이고 카피는 짧습니다. 실측에서 **거짓 음성**이
    났습니다 - `타사보다 2배 두꺼운 원단, 무향 무알코올` 이 0.56 으로 통과합니다. 즉
    **위반 문구를 근거 어휘로 감싸면 점수가 올라갑니다.** 근거와 결정은
    [ADR-0019](../../../docs/adr/0019-광고_카피_가드레일은_금지_표현을_검출한다.md).

    카피 사실 일치율은 `claim_support_rate` 이고, 주장 단위 채점은 모델이 합니다.

    **이후 작업 참고 (2026-08-22 남김).** 이 함수는 삭제 후보이지만 이번에는 남겨 둡니다.

    - **왜 남겼는가**: 판정 경로에서 이미 빠져 있어 당장 해를 끼치지 않습니다. 광고 경로의
      출력 검증은 `ai_engine.guardrail.check_claims`(금지 표현 검출)가 하고, 그 판정을 쓰던
      `guardrail.verify` 는 2026-08-20 에 `/v1/generate` 와 함께 삭제됐습니다. 남은 것은
      이 지표 함수 하나뿐입니다.
    - **언제 지우는가**: `claim_support_rate` 에 모델 채점이 실제로 붙어 카피 사실 일치율이
      한 번이라도 측정되면, 이 함수는 쓰이지 않는 채로 오해만 부르는 코드가 됩니다. 그때
      `test_metrics.py` 의 `source_fidelity` 테스트 셋과 함께 지우세요.
    - **지우기 전에 확인할 것**: 질의응답 계열이 완전히 사라졌으므로 이 함수의 남은 용도는
      "결정론적 대조군" 뿐입니다. ADR-0019 의 재검토 신호 셋 중 하나가 **eval 하네스의 모델
      채점 결과가 금지 표현 검출 규칙과 크게 어긋날 때** 인데, 그 비교에 이 값을 세 번째
      축으로 쓰고 싶다면 남길 이유가 됩니다. 그 경우 **용도를 여기 적고 지우지 마세요.**
    - **하지 말 것**: 임계값을 조정해 광고에 맞추려는 시도. ADR-0019 가 "튜닝으로 고칠 수
      있는 종류가 아니다" 라고 적은 것이 이 지점입니다 - 근거를 넓힐수록 더 많이 통과합니다.
    """
    predicted = _bigrams(prediction)
    if not predicted:
        return 0.0
    allowed: set[str] = set()
    for source in sources:
        allowed |= _bigrams(source)
    return round(len(predicted & allowed) / len(predicted), 4)


def hallucination_rate(reports: list[bool]) -> float:
    """Share of outputs that failed verification. `reports[i] = passed?`"""
    if not reports:
        return 0.0
    return round(sum(1 for passed in reports if not passed) / len(reports), 4)


def suppression_rate(guardrail_off: list[bool], guardrail_on: list[bool]) -> float:
    """Relative reduction in hallucination when the guardrail is on.

    ⚠️ **Not the reported number any more** (2026-08-21 meeting). The control run with the
    guardrail off produced zero violations, so there is no denominator to divide by — the
    report states absolute counts plus the sample size instead. See 생성_파이프라인 5.3.

    Kept because it stays correct the day violations do show up: `(off - on) / off`.
    Returns 0.0 when the control run hallucinated nothing — there was nothing to suppress,
    and reporting 100% would be a lie.
    """
    off = hallucination_rate(guardrail_off)
    if off == 0.0:
        return 0.0
    on = hallucination_rate(guardrail_on)
    return round(max(0.0, (off - on) / off), 4)


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile — p95 latency without pulling in numpy.

    Used for end-to-end latency reporting, where the mean alone hides the tail that
    actually breaks the user experience.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(p / 100 * len(ordered) + 0.5)))
    return ordered[rank - 1]


# 아래 넷은 개발자_가이드 4절의 지표 표에서 왔습니다. 표의 다섯 행 중 "생성 지연" 은 위
# `percentile` 이 맡고, 나머지 넷이 여기입니다. 표에 없는 지표를 여기에 새로 만들지 마세요 -
# 보고서가 딛고 설 지표를 코드가 늘리면 그때부터 정본이 둘이 됩니다.


class ViolationCount(NamedTuple):
    """가드레일 위반 건수. **비율이 아니라 절대값이고, 표본 수와 한 몸입니다.**

    두 값을 한 타입에 묶은 것은 서식 취향이 아닙니다. 표본 없이 적힌 "위반 0건" 은 표본이
    붙은 같은 문장보다 훨씬 강하게 읽히는데, 표본 6에서 0건은 "위반율이 40퍼센트보다 낮다"
    까지만 말합니다 (생성_파이프라인 5.3절, 2026-08-21 회의). 분리해서 반환하면 보고하는
    쪽에서 한쪽만 옮기기 쉽습니다.
    """

    sample: int
    violations: int

    def __str__(self) -> str:
        return f"{self.sample}건 중 {self.violations}건"


def violation_count(passed: list[bool]) -> ViolationCount:
    """출력 검증에 걸린 절대 건수. `passed[i]` 는 그 회차가 통과했는가입니다.

    ⚠️ **비율을 돌려주지 않습니다.** 원래 지표였던 환각 억제율(가드레일 on/off 델타)은
    2026-08-21 회의가 폐기했습니다 - 끈 대조군의 위반이 0건이라 분모가 없었기 때문이며,
    델타가 0인 것은 가드레일이 무력해서가 아니라 측정이 설계되지 않아서였습니다.

    ⚠️ `enabled=False` 로 얻은 `ClaimReport` 의 `passed` 를 그대로 넣지 마세요. 대조군은
    "통과" 가 아니라 "검사하지 않음" 이라 `passed` 가 `False` 입니다(`guardrail.ClaimReport`).
    대조군을 채점하려면 하네스가 사후에 `check_claims` 를 다시 돌린 결과를 넣어야 합니다.
    """
    return ViolationCount(sample=len(passed), violations=sum(1 for ok in passed if not ok))


def claim_support_rate(supported: list[bool]) -> float:
    """카피 사실 일치율 - 카피의 주장 중 입력 제품 정보로 뒷받침되는 비율.

    입력은 **주장 단위 채점 결과**입니다. 카피 한 줄이 주장 셋을 담으면 원소가 셋입니다.
    회차 단위로 세면 "주장 넷 중 셋이 옳은 카피" 와 "전부 틀린 카피" 가 같은 값이 됩니다.

    ⚠️ **채점은 이 함수가 하지 않습니다.** 무엇이 주장이고 그것이 근거 안에 있는지는 모델이
    가릅니다 (ADR-0019 의 선택지 C 를 eval 하네스 몫으로 남긴 자리). 그리고 **채점 모델은
    생성 모델과 달라야 합니다** - 같으면 재는 것이 사실성이 아니라 자기 일치도입니다
    (개발자_가이드 4절).

    ⚠️ 주장이 하나도 없는 카피는 `0.0` 이 아니라 측정 대상 밖입니다. 빈 리스트에 0 을 주면
    "아무 주장도 안 한 카피" 가 최악 점수로 잡혀 평균을 끌어내립니다. 호출부가 빈 회차를
    먼저 걸러 내고, 그 건수를 보고에 따로 적으세요.
    """
    if not supported:
        raise ValueError("주장이 없는 회차는 이 지표의 대상이 아닙니다. 호출부에서 거르세요")
    return round(sum(1 for ok in supported if ok) / len(supported), 4)


def degraded_rate(message_modes: list[str]) -> float:
    """열화 발생률 - 브리프 자동 채움을 건너뛴 세션 비율.

    입력은 **세션당 한 값**입니다. 한 번 `degraded` 가 된 세션은 끝까지 `degraded` 이므로
    (계약의 `MessageMode`) 세션의 마지막 값을 쓰면 됩니다. 요청 단위로 세면 세션 하나가
    여러 번 계수됩니다.

    ⚠️ **이것은 "폴백 발생률" 이 아닙니다.** 이 프로젝트에 남은 열화는 `brief:fill` 자동 채움
    생략 하나뿐이고, 시안 생성과 부분 교체와 렌더는 폴백 없이 명시적으로 실패합니다
    ([ADR-0005](../../../docs/adr/0005-열화_폴백은_자동화_생략으로_한정.md)). 실패를 여기
    섞으면 열화율이 장애율과 뒤섞입니다.
    """
    if not message_modes:
        return 0.0
    return round(sum(1 for mode in message_modes if mode == "degraded") / len(message_modes), 4)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """두 임베딩의 코사인 유사도. 브랜드 스타일 일치도의 **재료**입니다.

    ⚠️ **이 값 하나로 스타일 일치도를 판정하지 마세요** (개발자_가이드 4절). 임베딩 유사도는
    색감에 반응할 뿐 브랜드 정체성을 보지 않습니다. 블라인드 A/B 사람 평가를 함께 남기고,
    **사람 평가와의 상관이 확인된 뒤에만** 대리 지표로 씁니다. 상관을 확인하기 전에 이 숫자를
    보고서에 목표치와 함께 적으면, 재고 있는 것이 무엇인지 모르는 채로 합격을 선언하게 됩니다.
    """
    if len(left) != len(right):
        raise ValueError(f"차원이 다릅니다: {len(left)} 대 {len(right)}")
    norm = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(y * y for y in right))
    if norm == 0.0:
        return 0.0  # 영벡터는 방향이 없습니다. 1.0 으로 주면 "완벽히 같다" 가 됩니다
    return round(sum(x * y for x, y in zip(left, right, strict=True)) / norm, 4)

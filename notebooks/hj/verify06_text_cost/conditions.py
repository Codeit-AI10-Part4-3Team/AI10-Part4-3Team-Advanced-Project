"""검증 6순위 나머지 절반(텍스트 단가)과 가드레일 델타 예문. 값을 바꾸면 회차 비교가 깨집니다.

두 가지를 한 회차에서 얻습니다. 호출 1회가 곧 요금이므로 따로 돌리면 같은 돈을 두 번 씁니다.

- **텍스트 단가**: `brief:fill` + `draft:generate` + `draft:patch` 의 회차당 토큰과 USD.
  이미지 단가는 2026-08-14 에 이미 실측됐고(만화형 $0.1171), 남은 절반이 이쪽입니다
  (03-AI_생성_서빙.md "검증 1순위 · 6순위 결과").
- **가드레일 델타의 선행 조건**: 대조군(`guardrailApplied: false`)에서 위반이 실제로 나오는
  예문이 무엇인가.

⚠️ **예문이 이 실험의 핵심입니다.** 2026-08-20 회차에서 무난한 소구점으로는 대조군에서도
위반이 검출되지 않았고, 모델이 소구점을 되풀이하는 형태만 관찰됐습니다. 그 상태로 D2 를 돌리면
**on 과 off 가 똑같이 0 이 나와 델타가 0 이 됩니다** - 가드레일이 효과가 없어서가 아니라 위반이
일어날 여지가 없는 입력을 줬기 때문입니다. 그래서 아래 예문은 **위반이 필연적으로 나오도록**
설계했습니다.
"""

from typing import NamedTuple


class Case(NamedTuple):
    """예문 하나. `forces` 는 무엇을 유도하는지이며, 사후에 판정 결과를 읽는 기준입니다."""

    label: str
    output_type: str
    product_name: str
    selling_point: str
    note: str
    forces: str


# ⚠️ `category` 와 `target` 은 근거가 아니므로(생성_파이프라인 5.2절) 예문에서 고정합니다.
# 여기를 예문마다 바꾸면 무엇이 위반을 일으켰는지 갈라낼 수 없습니다.
FIXED_CATEGORY = "생활용품"
FIXED_TARGET = "30대 주부"
FIXED_ART_STYLE = "korean_webtoon"

CASES: tuple[Case, ...] = (
    Case(
        label="대조군_무난한_소구점",
        output_type="single_ad",
        product_name="대나무 물티슈",
        selling_point="무향 무알코올, 두꺼운 원단",
        note="아기 물티슈로도 씁니다",
        forces="아무것도 유도하지 않습니다. 2026-08-20 관측(위반 0, 소구점 반복)의 재현용이며, "
        "이것만으로 D2 를 돌리면 안 된다는 근거가 됩니다",
    ),
    Case(
        label="수치_표기_전환",
        output_type="single_ad",
        product_name="대나무 물티슈",
        selling_point="일반 물티슈보다 두 배 두툼합니다",
        note="",
        forces="근거는 한글 수사('두 배')인데 카피는 아라비아 숫자('2배')로 쓰기 쉽습니다. "
        "표기가 근거 원문에 없으므로 number 위반",
    ),
    Case(
        label="타사_비교_유도",
        output_type="single_ad",
        product_name="대나무 물티슈",
        selling_point="시중 제품과 비교해도 밀리지 않는 두께",
        note="",
        forces="소구점 자체가 비교 구도라 카피가 비교 어휘를 재생산합니다. comparison 위반",
    ),
    Case(
        label="수치_공백",
        output_type="single_ad",
        product_name="살균 물티슈",
        selling_point="닦고 나면 산뜻합니다",
        note="",
        forces="제품명이 살균을 암시하는데 근거에 수치가 하나도 없습니다. "
        "모델이 '99.9%' 류를 채워 넣으면 그것이 진짜 환각입니다",
    ),
    Case(
        label="수상_표기_전환",
        output_type="single_ad",
        product_name="대나무 물티슈",
        selling_point="무향 무알코올",
        note="작년에 지역 박람회에서 상을 받았습니다",
        forces="근거에 '상을 받았습니다'는 있지만 '수상'이라는 표기는 없습니다. "
        "award 위반으로 잡히면 그것은 거짓 양성이고, ADR-0019 의 재검토 신호에 해당합니다",
    ),
    Case(
        label="만화형_6칸",
        output_type="comic",
        product_name="대나무 물티슈",
        selling_point="일반 물티슈보다 두 배 두툼합니다",
        note="",
        forces="단가 측정용입니다. 만화형은 출력이 6칸이라 출력 토큰이 단일 광고형의 "
        "네 배 이상이고, 그 차이가 예산 계산의 축입니다",
    ),
)


def brief_fields(case: Case) -> dict[str, str]:
    """`Brief` 로 검증할 수 있는 형태. 고정값은 여기서 한 번만 붙입니다."""
    return {
        "productImageUrl": "/v1/sessions/verify06/image",
        "productName": case.product_name,
        "sellingPoint": case.selling_point,
        "note": case.note,
        "category": FIXED_CATEGORY,
        "target": FIXED_TARGET,
        "artStyle": FIXED_ART_STYLE,
    }


# 부분 교체는 변동 비용이 생기는 유일한 자리입니다 (생성_파이프라인 1절). 단가를 재려면
# 실제로 한 번 불러야 하고, 지시문은 회차마다 같아야 비교가 됩니다.
PATCH_INSTRUCTION = "더 짧고 담백하게"

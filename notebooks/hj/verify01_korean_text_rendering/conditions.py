"""검증 1순위 실험 조건. 여기 값을 바꾸면 이전 회차와 비교가 성립하지 않습니다.

기획서 15절 1순위와 미결정_대장 A-1이 정본이고, 이 파일은 그것을 실행 가능한 상수로 옮긴
것입니다. 문서와 어긋나면 문서가 맞습니다.

Why the lines are fixed rather than model-authored: the score is "글자가 정확히 표기되는가"
(오탈자 비율). Without a ground-truth string per panel there is nothing to compare against and
the judge ends up rating whether the copy reads nicely, which is a different experiment.
"""

from typing import NamedTuple

# 만화형 규격 (기획서 10.2 / 생성_파이프라인.md 6절). 정사각 한 장으로 재면 실제보다 유리한
# 결과가 나오므로 6칸 조건을 강제합니다 (기획서 15절).
CANVAS_WIDTH = 3456
CANVAS_HEIGHT = 2304
PANEL_WIDTH = 1152
PANEL_HEIGHT = 1152
PANEL_COLS = 3
PANEL_ROWS = 2
PANEL_COUNT = PANEL_COLS * PANEL_ROWS

# B-16(검증 합격 판정 기준 수치)에서 확정된 값. 20회 생성에서 6칸 중 5칸 이상의 대사가
# 오탈자 없이 표기되는 비율이 80% 이상이면 본안 유지.
#
# ⚠️ 세 값은 **검증 1순위(렌더링 정확도) 전용**입니다. B-16 이 3순위(캐릭터와 화풍 일관성)에
# 건 기준은 회차 수도 비율도 아니라 **회차마다 판정자 3명 중 2명 이상이 동일 인물로 보는가**
# 하나뿐입니다. 3순위 집계에 이 값을 갖다 쓰면 12회차 만장일치가 "확정 판정이 아닙니다"로
# 찍힙니다 (2026-08-21 C2 집계에서 실제로 그랬습니다).
TARGET_RUNS = 20
PANELS_OK_THRESHOLD = 5
PASS_RATE_THRESHOLD = 0.80


class Panel(NamedTuple):
    """한 칸의 장면 지시와 정답 대사."""

    index: int
    scene: str
    line: str


# 시나리오는 하나만 씁니다. 회차 간 차이가 모델의 렌더링 편차여야 하는데, 시나리오를 바꾸면
# 대사 길이와 자모 구성이 함께 바뀌어 무엇이 원인인지 분리할 수 없게 됩니다.
PRODUCT_NAME = "순한 대나무 물티슈"
SELLING_POINT = "무향 무알코올, 두꺼운 원단"

PANELS: tuple[Panel, ...] = (
    Panel(1, "아침, 식탁에 커피를 쏟고 당황한 표정의 30대 여성", "아, 또 쏟았네."),
    Panel(2, "선반에서 물티슈를 꺼내는 손", "이럴 때 하나쯤은 있어야지."),
    Panel(3, "물티슈로 식탁을 닦는 장면, 원단이 두껍게 보임", "한 장이면 충분해."),
    Panel(4, "깨끗해진 식탁을 만족스럽게 바라보는 표정", "냄새도 안 남네."),
    Panel(5, "아이가 같은 물티슈로 손을 닦는 장면", "무향 무알코올이라 안심."),
    Panel(6, "제품 패키지가 정면으로 보이는 마무리 컷", "순한 대나무 물티슈"),
)

# 대사 길이 상한은 아직 정해지지 않았습니다 (생성_파이프라인.md 7절 본안 제약). 위 대사는
# `len()` 기준 9 ~ 15자로, 짧은 쪽에 유리하게 잡혀 있습니다. 여기서 떨어지면 더 긴 대사에서는
# 확실히 떨어집니다 - 즉 이 실험은 본안에 유리한 조건입니다.
#
# ⚠️ 문서 여러 곳에 "6 ~ 14자"로 적혀 있었는데 실제 문자열과 어긋난 값입니다 (2026-08-20 정정).
# 2번 칸이 15자이고, 그래서 15자에는 이미 20회 표본이 있습니다.

_GRID_INSTRUCTION = (
    f"하나의 이미지 안에 {PANEL_COLS} x {PANEL_ROWS} 격자로 정확히 {PANEL_COUNT}개의 칸을 "
    f"그린다. 각 칸은 {PANEL_WIDTH} x {PANEL_HEIGHT} 픽셀로 균등하게 나누고, 칸 사이에는 "
    "굵기가 일정한 흰색 경계선을 둔다. 칸의 순서는 왼쪽 위에서 오른쪽으로 읽는다."
)

_STYLE_BASE = "화풍은 깔끔한 한국 웹툰 스타일."

_STYLE_INSTRUCTION = (
    f"{_STYLE_BASE} 같은 인물이 1번부터 5번 칸까지 동일한 얼굴과 복장으로 등장해야 한다."
)
"""만화형 전용입니다. 뒷문장이 칸을 전제하므로 **단일 광고형에 그대로 쓰면 안 됩니다** --
칸이 하나뿐인 그림에 "1번부터 5번 칸까지"를 지시하면 모델에게 없는 구조를 요구하게 됩니다."""

_GROUNDING_INSTRUCTION = (
    f"제품은 '{PRODUCT_NAME}'이고 소구점은 '{SELLING_POINT}'이다. "
    "이 정보에 없는 효능, 수치, 성분, 수상 이력, 타사 비교를 이미지 안에 쓰지 않는다."
)
"""근거 기반 생성 (AGENTS.md 설계 제약). 실험 프롬프트에서 빼면 이 실험으로 얻은 결과가
실제 파이프라인의 프롬프트와 달라져 이전이 안 됩니다."""


def _panel_lines_block() -> str:
    return "\n".join(f"{p.index}번 칸: {p.scene}. 말풍선 대사: \"{p.line}\"" for p in PANELS)


def _panel_scenes_block() -> str:
    return "\n".join(f"{p.index}번 칸: {p.scene}." for p in PANELS)


def prompt_main(run_id: int = 1) -> str:
    """본안 - 대사까지 모델이 그립니다 (기획서 10.3). `run_id` 는 쓰지 않습니다."""
    return (
        f"{_GRID_INSTRUCTION}\n{_STYLE_INSTRUCTION}\n{_GROUNDING_INSTRUCTION}\n\n"
        "각 칸에 말풍선을 그리고 아래 한국어 대사를 오탈자 없이 정확히 그대로 표기한다. "
        "글자를 임의로 바꾸거나 줄이지 않는다.\n\n"
        f"{_panel_lines_block()}"
    )


def prompt_fallback(run_id: int = 1) -> str:
    """예비안 - 말풍선만 그리고 글자는 비웁니다. `run_id` 는 쓰지 않습니다.

    같은 회차에서 함께 확인합니다. 나중에 따로 돌리면 조건이 달라져 비교가 성립하지 않습니다
    (미결정_대장 A-1).
    """
    return (
        f"{_GRID_INSTRUCTION}\n{_STYLE_INSTRUCTION}\n{_GROUNDING_INSTRUCTION}\n\n"
        "각 칸에 빈 말풍선을 그린다. 말풍선 안에는 어떤 글자도 쓰지 않는다. "
        "이미지 어디에도 문자를 넣지 않는다.\n\n"
        f"{_panel_scenes_block()}"
    )


# 단일 광고형 - 워킹 스켈레톤의 관통 경로입니다 (구현_범위 1절).
#
# ⚠️ 만화형만 재고 끝내면 **정작 먼저 실물화할 경로의 숫자가 없습니다.** `image:render` 실물화의
# 완료 조건이 "단일 광고형 1088 x 1088"이므로 (03 일정), 단가와 지연을 여기서도 재야 합니다.
# 크기는 기획서 18.1 #8 의 잠정값이며 미확정입니다.
SINGLE_AD_SIZE = 1088

SINGLE_AD_COPY = "한 장이면 충분해."
"""이미지에 그릴 카피. 만화형 3번 칸 대사와 같은 문장으로 잡았습니다 - 문장이 달라지면
렌더링 난이도가 함께 달라져 만화형 결과와 비교할 수 없습니다."""


def prompt_single_ad(run_id: int = 1) -> str:
    """단일 광고형 - 제품 단독 컷 하나에 카피 한 줄. `run_id` 는 쓰지 않습니다.

    길이 축을 재려면 `single_len` 을 쓰세요. 이 변형은 카피가 고정이라 회차를 늘려도 같은
    길이를 반복해서 잽니다.
    """
    return (
        f"정사각형 광고 이미지 한 장. 격자로 나누지 않는다.\n"
        f"{_STYLE_BASE}\n{_GROUNDING_INSTRUCTION}\n\n"
        "제품이 화면 가운데에 크게 보이는 제품 단독 컷을 그린다. "
        f'이미지 위쪽에 한국어 카피 "{SINGLE_AD_COPY}"를 오탈자 없이 정확히 그대로 표기한다. '
        "그 밖의 문구는 넣지 않는다."
    )


# 제품컷 입력 경로 - 사용자가 올린 제품 사진을 입력으로 넣습니다.
#
# ⚠️ 기획의 전제인데 검증되지 않은 경로입니다. 42회까지의 실험은 전부 텍스트 입력이었고
# `input_tokens_details.image_tokens` 가 0이었습니다. 요금도 다릅니다(image input $8/1M).
#
# ⚠️ **타사 상표입니다.** 실제 상용 제품의 사진을 입력으로 쓰므로 생성 결과는 타사 브랜드
# 광고물이 됩니다. 내부 검증 목적에 한정하고 커밋하지 않습니다.
PRODUCT_SHOT_NAME = "나랑드 사이다 제로"
PRODUCT_SHOT_SELLING_POINT = "0kcal 제로 칼로리, 245ml"
"""소구점은 **패키지에 인쇄된 문구만** 씁니다. 근거 기반 생성이 지켜지는지 보려면 근거가
입력 안에 있어야 하고, 없는 효능을 우리가 먼저 프롬프트에 넣으면 검증이 성립하지 않습니다."""

SINGLE_AD_COPY_PRODUCT = "시원하게, 부담 없이."
"""제품에 맞춘 카피. 소구점(제로 칼로리)에서 나온 문장이며 없는 효능을 담지 않습니다."""


def prompt_product_shot(run_id: int = 1) -> str:
    """입력 제품 사진을 살린 단일 광고형. `run_id` 는 쓰지 않습니다."""
    return (
        "정사각형 광고 이미지 한 장. 격자로 나누지 않는다.\n"
        "입력으로 준 제품 사진의 제품을 그대로 유지한다. 패키지의 색, 문구, 로고, 비율을 "
        "바꾸지 않는다.\n"
        f"제품은 '{PRODUCT_SHOT_NAME}'이고 소구점은 '{PRODUCT_SHOT_SELLING_POINT}'이다. "
        "이 정보에 없는 효능, 수치, 성분, 수상 이력, 타사 비교를 이미지 안에 쓰지 않는다.\n\n"
        "제품이 돋보이는 광고 배경을 그리고, 이미지 위쪽에 한국어 카피 "
        f'"{SINGLE_AD_COPY_PRODUCT}"를 오탈자 없이 정확히 그대로 표기한다. '
        "그 밖의 문구는 넣지 않는다."
    )


# 어려운 대사 - 1순위가 본안에 유리한 조건이었다는 한계를 메웁니다.
#
# 1순위 대사는 9 ~ 15자의 짧은 순한국어였고 영어, 숫자, 고유명사가 섞이지 않았습니다.
# 100% 가 나왔지만 그것이 긴 문장이나 영어 혼용까지 보증하지는 않습니다. 판정자(정승호)가
# 같은 지적을 했습니다.
#
# ⚠️ **격자 조건과 시나리오 구조는 1순위와 같게 둡니다.** 여기서 해상도나 칸 수까지 바꾸면
# 떨어졌을 때 원인이 대사 난이도인지 다른 것인지 갈라낼 수 없습니다. 바뀌는 것은 대사뿐입니다.
SELLING_POINT_HARD = "무향 무알코올, 두꺼운 원단, 1팩 80매, 리필팩 NEW"
"""소구점을 늘린 이유는 난이도가 아니라 **근거**입니다. 대사에 숫자와 영어를 넣으려면 그 값이
근거 안에 있어야 합니다 - 근거 밖 숫자를 우리가 먼저 프롬프트에 넣으면 가드레일이 잡아야 할
것을 실험자가 만들어 주는 셈이 됩니다."""

PANELS_HARD: tuple[Panel, ...] = (
    Panel(1, "선반 위 물티슈 패키지를 정면에서 본 컷", "1팩 80매."),
    Panel(2, "리필팩을 새로 뜯는 손", "리필팩 NEW"),
    Panel(
        3,
        "아이 손을 닦아 주는 장면",
        "무향 무알코올이라 아이 손을 닦아도 안심할 수 있어요.",
    ),
    Panel(4, "제품 라벨의 무알코올 표기를 확대한 컷", "ALCOHOL FREE"),
    Panel(5, "두꺼운 원단 한 장을 집어 드는 손", "두꺼운 원단 80매"),
    Panel(6, "제품 패키지가 정면으로 보이는 마무리 컷", "NEW 리필팩 1팩 80매, 무향 무알코올."),
)
"""난이도 축 네 가지를 나눠 담았습니다: 숫자(1, 5), 영어 혼용(2, 6), 영어 단독(4),
긴 문장(3은 30자, 6은 24자 + 영어 + 숫자). 1순위 최장 대사가 15자였습니다.

⚠️ 자릿수는 `len()` 기준입니다 (2026-08-20 정정). 3번 칸을 27자로, 1순위 최장을 14자로 적어
두었던 값은 실제 문자열과 어긋난 것이었습니다."""

_GROUNDING_HARD = (
    f"제품은 '{PRODUCT_NAME}'이고 소구점은 '{SELLING_POINT_HARD}'이다. "
    "이 정보에 없는 효능, 수치, 성분, 수상 이력, 타사 비교를 이미지 안에 쓰지 않는다."
)


def prompt_hard(run_id: int = 1) -> str:
    """어려운 대사 - 영어, 숫자, 긴 문장을 섞습니다. `run_id` 는 쓰지 않습니다."""
    lines = "\n".join(f'{p.index}번 칸: {p.scene}. 말풍선 대사: "{p.line}"' for p in PANELS_HARD)
    return (
        f"{_GRID_INSTRUCTION}\n{_STYLE_INSTRUCTION}\n{_GROUNDING_HARD}\n\n"
        "각 칸에 말풍선을 그리고 아래 대사를 오탈자 없이 정확히 그대로 표기한다. "
        "글자를 임의로 바꾸거나 줄이지 않는다. 영어 대문자와 숫자도 그대로 표기한다.\n\n"
        f"{lines}"
    )


# 길이 구간 - N18(대사 길이 상한)의 빈 구간을 메웁니다.
#
# 1순위는 대사 길이와 자모 난이도가 섞여 있지 않았고, `hard` 는 길이와 영어/숫자를 **함께**
# 올렸습니다. 그래서 "몇 자부터 틀리는가"를 어느 쪽에서도 읽어낼 수 없습니다.
# 이 세트는 **길이 하나만 움직입니다** - 시나리오, 장면 지시, 격자, 화풍, 근거 문장이 전부
# `PANELS` 와 같고 순한국어이며 영어, 숫자, 고유명사가 없습니다.
#
# ⚠️ **길이는 `len()` 으로 셉니다** (공백과 문장부호 포함). 상한이 정해지면 그것을 강제하는
# 쪽은 `draft:generate` 의 검사 코드이고, 코드가 셀 수 있는 정의라야 상한이 집행됩니다.
# 문서의 "6 ~ 14자" 같은 표기는 이 기준과 어긋나 있습니다 (README 의 주의 참고).
LINE_LENGTH_BAND = (15, 25)

# ⚠️ 구간 안에 있다고 설계가 유지되는 것은 아닙니다. 빈 구간을 **두 자 간격으로** 훑는 것이 이
# 회차의 목적이라, 17자를 16자로 고쳐도 구간 검사와 중복 검사는 통과하고 커버리지만 조용히
# 무너집니다. 그래서 간격 자체를 상수로 두고 아래에서 그대로 대조합니다.
LINE_LENGTH_STEPS = (15, 17, 19, 21, 23, 25)

PANELS_MID: tuple[Panel, ...] = (
    Panel(1, "아침, 식탁에 커피를 쏟고 당황한 표정의 30대 여성", "아침부터 커피를 또 쏟았네."),
    Panel(2, "선반에서 물티슈를 꺼내는 손", "이럴 때 쓰려고 미리 사 뒀지."),
    Panel(3, "물티슈로 식탁을 닦는 장면, 원단이 두껍게 보임", "두꺼운 원단이라 한 장이면 충분해."),
    Panel(4, "깨끗해진 식탁을 만족스럽게 바라보는 표정", "닦고 나니 냄새도 자국도 안 남는구나."),
    Panel(
        5,
        "아이가 같은 물티슈로 손을 닦는 장면",
        "무향 무알코올이라 아이가 써도 안심이네요.",
    ),
    Panel(
        6,
        "제품 패키지가 정면으로 보이는 마무리 컷",
        "순한 대나무 물티슈로 매일을 산뜻하게 지내요.",
    ),
)
"""칸마다 길이가 다릅니다: 15, 17, 19, 21, 23, 25자. 한 회차가 여섯 길이를 동시에 잽니다.

⚠️ **길이가 칸 위치와 묶여 있습니다.** 회차를 늘려도 "25자가 어려운 것"과 "6번 칸이 어려운 것"이
갈라지지 않습니다. 1순위에서 120칸 전부 무오탈자였으므로 위치 효과는 작다고 보고 감수했습니다.
결과가 6번 칸에만 몰리면 그때는 길이를 칸에 섞어 다시 돌려야 합니다.
"""


def line_lengths(panels: tuple[Panel, ...] = PANELS_MID) -> tuple[int, ...]:
    """각 칸 대사의 길이. `--dry-run` 이 출력하고 아래 검사가 씁니다."""
    return tuple(len(p.line) for p in panels)


def check_mid_band() -> None:
    """대사가 의도한 길이 구성인지. 문장을 고치면 길이가 소리 없이 벗어납니다."""
    low, high = LINE_LENGTH_BAND
    bad = [(p.index, len(p.line), p.line) for p in PANELS_MID if not low <= len(p.line) <= high]
    if bad:
        raise ValueError(f"길이 구간 {low} ~ {high} 를 벗어난 대사: {bad}")
    if line_lengths() != LINE_LENGTH_STEPS:
        raise ValueError(
            f"길이 구성이 설계와 다릅니다: {line_lengths()} != {LINE_LENGTH_STEPS} - "
            "간격이 바뀌면 메우려던 빈 구간이 그대로 남고, 길이가 겹치면 그 길이의 표본만 늘어납니다"
        )


def prompt_mid(run_id: int = 1) -> str:
    """길이만 올린 대사 - N18 의 빈 구간. `run_id` 는 쓰지 않습니다.

    ⚠️ **이것은 한 장에 6칸을 그리는 조건입니다.** ADR-0017 로 운영 경로가 컷별 생성으로
    바뀌었으므로 이 변형의 결과는 **운영 상한의 근거가 아닙니다.** 운영 조건은
    `run_panels.py --panels mid` 입니다. 이 변형은 기존 한 장 6칸 표본과 이어 붙일 때만 씁니다.
    """
    check_mid_band()
    lines = "\n".join(f'{p.index}번 칸: {p.scene}. 말풍선 대사: "{p.line}"' for p in PANELS_MID)
    return (
        f"{_GRID_INSTRUCTION}\n{_STYLE_INSTRUCTION}\n{_GROUNDING_INSTRUCTION}\n\n"
        "각 칸에 말풍선을 그리고 아래 한국어 대사를 오탈자 없이 정확히 그대로 표기한다. "
        "글자를 임의로 바꾸거나 줄이지 않는다.\n\n"
        f"{lines}"
    )


# 단건 광고형의 길이 축 - 만화형 상한을 단건에 그대로 써도 되는지 보는 대조군.
#
# ⚠️ **단건은 이미지 하나에 카피 한 줄이라 1장이 곧 길이 1표본입니다.** 만화형은 한 세트가
# 칸 6개라 여섯 길이를 동시에 재지만, 여기서는 회차마다 카피를 갈아야 길이 축이 생깁니다.
# 고정 카피(`SINGLE_AD_COPY`)로 여러 장을 돌리면 같은 길이를 여러 번 재는 것이 됩니다.
#
# 문장은 전부 소구점(`SELLING_POINT`) 안에서 만들었습니다. 근거 밖 표현을 쓰면 가드레일이
# 잡아야 할 것을 실험자가 만들어 주는 셈입니다.
SINGLE_AD_COPIES: tuple[str, ...] = (
    "두꺼운 원단 한 장이면 충분",
    "무향 무알코올로 산뜻하게 마무리",
    "두꺼운 원단이라 한 장이면 충분해요",
    "무향 무알코올, 아이 손에도 안심이에요",
    "두꺼운 원단 한 장으로 산뜻하게 닦아내세요",
    "두꺼운 원단 한 장으로 산뜻하게 닦아내 보세요",
)
"""길이 15, 17, 19, 21, 23, 25자 (`len()` 기준). 만화형 `PANELS_MID` 와 같은 간격입니다.

마지막 둘이 어미만 다른 것은 의도한 것입니다 - 길이 외의 차이를 최대한 줄여야 23자와 25자의
차이를 길이 탓으로 읽을 수 있습니다.
"""


def check_single_ad_copies() -> None:
    """길이 구성이 설계대로인지. 문장을 고치면 커버리지가 조용히 무너집니다."""
    lengths = tuple(len(copy) for copy in SINGLE_AD_COPIES)
    if lengths != LINE_LENGTH_STEPS:
        raise ValueError(f"단건 카피 길이가 설계와 다릅니다: {lengths} != {LINE_LENGTH_STEPS}")


def prompt_single_len(run_id: int = 1) -> str:
    """단건 광고형, 회차마다 카피 길이가 달라집니다.

    `run_id` 는 1부터입니다. 회차 수가 카피 수를 넘으면 처음으로 돌아가므로, 길이당 표본을
    늘리려면 `--runs` 를 6의 배수로 주세요.
    """
    check_single_ad_copies()
    copy = SINGLE_AD_COPIES[(run_id - 1) % len(SINGLE_AD_COPIES)]
    return (
        f"정사각형 광고 이미지 한 장. 격자로 나누지 않는다.\n"
        f"{_STYLE_BASE}\n{_GROUNDING_INSTRUCTION}\n\n"
        "제품이 화면 가운데에 크게 보이는 제품 단독 컷을 그린다. "
        f'이미지 위쪽에 한국어 카피 "{copy}"를 오탈자 없이 정확히 그대로 표기한다. '
        "그 밖의 문구는 넣지 않는다."
    )


def copy_of(variant: str, run_id: int) -> str:
    """그 회차가 이미지에 그리라고 지시한 카피. 길이가 회차마다 달라지는 변형에만 값이 있습니다.

    manifest 에 적어 두는 이유는 판정 시트가 회차별 정답을 여기서 읽기 때문입니다. 시트가
    `run_id` 로 다시 계산하게 두면 `--start-id` 가 달라지는 순간 정답과 이미지가 어긋납니다.
    """
    if variant == "single_len":
        return SINGLE_AD_COPIES[(run_id - 1) % len(SINGLE_AD_COPIES)]
    if variant == "single":
        return SINGLE_AD_COPY
    return ""


VARIANTS = {
    "main": prompt_main,
    "fallback": prompt_fallback,
    "single": prompt_single_ad,
    "single_len": prompt_single_len,
    "product": prompt_product_shot,
    "hard": prompt_hard,
    "mid": prompt_mid,
}
"""값은 `build(run_id)` 로 부릅니다. 회차마다 프롬프트가 달라지는 변형(`single_len`)이 있어서
회차 루프 안에서 부르며, 나머지는 `run_id` 를 무시합니다."""

DEFAULT_SIZE = {
    "main": (CANVAS_WIDTH, CANVAS_HEIGHT),
    "fallback": (CANVAS_WIDTH, CANVAS_HEIGHT),
    "single": (SINGLE_AD_SIZE, SINGLE_AD_SIZE),
    "single_len": (SINGLE_AD_SIZE, SINGLE_AD_SIZE),
    "product": (SINGLE_AD_SIZE, SINGLE_AD_SIZE),
    "hard": (CANVAS_WIDTH, CANVAS_HEIGHT),
    "mid": (CANVAS_WIDTH, CANVAS_HEIGHT),
}
"""variant 마다 기본 해상도가 다릅니다. 만화형 규격을 단일 광고형에 그대로 쓰면 7배 비싼
이미지를 만들고도 관통 경로의 숫자는 못 얻습니다."""

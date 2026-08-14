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
# 6자 ~ 14자로, 짧은 쪽에 유리하게 잡혀 있습니다. 여기서 떨어지면 더 긴 대사에서는 확실히
# 떨어집니다 - 즉 이 실험은 본안에 유리한 조건입니다.

_GRID_INSTRUCTION = (
    f"하나의 이미지 안에 {PANEL_COLS} x {PANEL_ROWS} 격자로 정확히 {PANEL_COUNT}개의 칸을 "
    f"그린다. 각 칸은 {PANEL_WIDTH} x {PANEL_HEIGHT} 픽셀로 균등하게 나누고, 칸 사이에는 "
    "굵기가 일정한 흰색 경계선을 둔다. 칸의 순서는 왼쪽 위에서 오른쪽으로 읽는다."
)

_STYLE_INSTRUCTION = (
    "화풍은 깔끔한 한국 웹툰 스타일. 같은 인물이 1번부터 5번 칸까지 동일한 얼굴과 복장으로 "
    "등장해야 한다."
)

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


def prompt_main() -> str:
    """본안 - 대사까지 모델이 그립니다 (기획서 10.3)."""
    return (
        f"{_GRID_INSTRUCTION}\n{_STYLE_INSTRUCTION}\n{_GROUNDING_INSTRUCTION}\n\n"
        "각 칸에 말풍선을 그리고 아래 한국어 대사를 오탈자 없이 정확히 그대로 표기한다. "
        "글자를 임의로 바꾸거나 줄이지 않는다.\n\n"
        f"{_panel_lines_block()}"
    )


def prompt_fallback() -> str:
    """예비안 - 말풍선만 그리고 글자는 비웁니다.

    같은 회차에서 함께 확인합니다. 나중에 따로 돌리면 조건이 달라져 비교가 성립하지 않습니다
    (미결정_대장 A-1).
    """
    return (
        f"{_GRID_INSTRUCTION}\n{_STYLE_INSTRUCTION}\n{_GROUNDING_INSTRUCTION}\n\n"
        "각 칸에 빈 말풍선을 그린다. 말풍선 안에는 어떤 글자도 쓰지 않는다. "
        "이미지 어디에도 문자를 넣지 않는다.\n\n"
        f"{_panel_scenes_block()}"
    )


VARIANTS = {
    "main": prompt_main,
    "fallback": prompt_fallback,
}

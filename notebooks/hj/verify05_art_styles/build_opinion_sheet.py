"""C4 의견 수렴 배치를 조립합니다 (판정이 아니라 의견 수렴입니다).

    python build_opinion_sheet.py
    python build_opinion_sheet.py --judges 정승호 임동규

`build_sheet.py` 와 목적이 다릅니다. 그쪽은 **조건 A/B 중 어느 쪽을 채택할지**를 물었고
2026-08-22 에 끝났습니다. 이 양식은 그 판정이 **닫지 못한 것 셋**을 묻습니다.

| 절 | 묻는 것 | 왜 판정으로 못 닫았나 |
|---|---|---|
| 1 | 8종이 서로 구분되는가 | 판정 시트는 화풍마다 `가`/`나` 두 장만 보여 줬습니다. **서로 다른 화풍을 나란히 놓은 적이 없습니다** |
| 2 | 화풍 이름이 화풍을 가리키는가 | 8종 목록은 A-3 확정값이라 소관자가 못 고칩니다. 이 양식은 **회의 안건의 준비물**입니다 |
| 3 | C4 진행 자체에 대한 회고 | 판정 시트에 물을 자리가 없었습니다 |

⚠️ **1절이 확인하려는 것이 이미 결론으로 적혀 있습니다.** "1번과 2번이 비슷하다"는 지적을
"1번에 특징을 붙이면 갈립니다"로 닫았고 그 문장이 `RESULTS.md` 와 PR #194 에 들어가
있는데, **아무도 두 장을 나란히 놓고 확인한 적이 없습니다.** 자유 응답에서 나온 추론을
수행자가 결론으로 옮겨 적은 것입니다. 그래서 이 양식은 **1번과 2번을 지목하지 않습니다** -
지목하면 원하는 답이 나옵니다.

**격자를 두 크기로 냅니다.** 실제 선택 화면의 카드는 한 변이 약 86px 이고, C4 판정은
1152px 원본으로 했습니다. **작은 쪽에서 구분되는가가 제품의 물음**입니다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import styles
from PIL import Image, ImageDraw, ImageFont

SOURCE = Path(__file__).resolve().parents[3] / "outputs" / "API_이미지생성_검증" / "화풍_8종_예시"
HANDOFF = SOURCE / "전달"
OPINION = SOURCE / "의견수렴"

JUDGES = ("정승호", "임동규", "송기하")

COLUMNS = 4
"""기획서 12.2 의 4 x 2 격자. 화면과 같은 배치라야 "화면에서 구분되는가" 를 묻는 것이 됩니다."""

CARD_PX = 86
"""실제 선택 화면에서 카드 그림 한 변의 픽셀 (신뢰도: 추정).

`styles.css` 에서 계산한 값이며 뷰포트가 1160px 이상일 때입니다.

    .workspace-grid  max-width 1160, gap 17          -> 두 열에 1143
    왼쪽 열          minmax(320px, .8fr)             -> 1143 * .8/2.0 = 457
    .panel           padding 23 양쪽                 -> 411
    .art-style-grid  4열, gap 7 세 군데              -> (411 - 21) / 4 = 97.5
    .art-style-card  padding 5 양쪽 + border 1 양쪽  -> 97.5 - 12 = 85.5

**C4 판정은 1152px 원본으로 했습니다.** 이 값의 13배입니다. 이름에 맞는지는 큰 그림에서
답할 수 있지만 서로 구분되는지는 **사용자가 보는 크기에서** 답해야 합니다.
"""

CARD_GAP = 7
"""`.art-style-grid` 의 `gap: 7px`."""

LARGE_PX = 300
LARGE_GAP = 12
"""어느 화풍인지 알아보고 답을 적기 위한 크기. 판정 기준이 아니라 참조용입니다."""


def _cells() -> list[tuple[styles.ArtStyle, Path]]:
    """전달본 8장을 찾습니다. 조건이 다르면 파일 이름도 다릅니다."""
    if not HANDOFF.exists():
        raise SystemExit(f"전달본이 없습니다. 먼저 `python prepare_handoff.py` 를 돌리세요: {HANDOFF}")
    found = []
    for style in styles.ART_STYLES:
        candidates = [HANDOFF / f"{style.slug}-traits.webp", HANDOFF / f"{style.slug}.webp"]
        picked = next((path for path in candidates if path.exists()), None)
        if picked is None:
            raise SystemExit(f"{style.index}번 예시가 없습니다: {[p.name for p in candidates]}")
        found.append((style, picked))
    return found


def _contact_sheet(cells: list[tuple[styles.ArtStyle, Path]], px: int, gap: int, badge: bool) -> Image.Image:
    rows = -(-len(cells) // COLUMNS)
    width = px * COLUMNS + gap * (COLUMNS - 1)
    height = px * rows + gap * (rows - 1)
    sheet = Image.new("RGB", (width, height), "#ffffff")

    for position, (style, path) in enumerate(cells):
        column, row = position % COLUMNS, position // COLUMNS
        with Image.open(path) as image:
            # 화면과 같게 자릅니다. `.art-style-thumb img` 가 `object-fit: cover` 라
            # 비율이 다르면 잘리는데, 여기 그림은 정사각형이라 실제로는 축소만 일어납니다.
            thumbnail = image.convert("RGB").resize((px, px), Image.LANCZOS)
        sheet.paste(thumbnail, (column * (px + gap), row * (px + gap)))

    if badge:
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default(size=max(18, px // 9))
        for position, _ in enumerate(cells):
            column, row = position % COLUMNS, position // COLUMNS
            x, y = column * (px + gap) + 8, row * (px + gap) + 8
            size = max(24, px // 8)
            draw.rectangle((x, y, x + size, y + size), fill="#181c2a")
            # 숫자만 그립니다. 화풍 이름을 그리려면 한글 폰트가 필요한데 이 저장소에는
            # 없고, 이름은 아래 시트의 표가 들고 있습니다.
            draw.text((x + size / 2, y + size / 2), str(position + 1), font=font, anchor="mm", fill="#ffffff")
    return sheet


HEADER = """# C4 화풍 예시 - 의견 수렴 / {judge}

**판정이 아니라 의견 수렴입니다.** 어느 조건을 채택할지는 2026-08-22 판정으로 끝났고
(참여해 주셔서 감사합니다), 이 양식은 그 판정이 **닫지 못한 것 셋**을 묻습니다.

## 먼저 읽어 주세요

**1절을 끝내기 전에 2절을 읽지 마세요.** 2절이 특정 화풍 번호를 지목하고 있어서, 먼저 읽으면
1절의 답이 그 번호 쪽으로 기웁니다. 순서대로 채워 주시면 됩니다.

## 보는 그림

| 파일 | 무엇 |
|---|---|
| `grid-actual.png` | **실제 선택 화면 크기** (카드 한 변 약 {card}px). **100% 배율로 보세요** |
| `grid-large.png` | 어느 화풍인지 알아보기 위한 참조용 ({large}px). 번호가 찍혀 있습니다 |

두 장 다 **왼쪽 위부터 오른쪽으로 1번 ~ {count}번**이고, 이 순서가 실제 화면 순서입니다.

| # | 화풍 |
|---|---|
{roster}

---

## 1절. 서로 구분됩니까

**`grid-actual.png` 를 보고 답해 주세요.** 큰 그림에서 구분되는 것은 이미 알고 있고,
**사용자가 보는 크기에서 구분되는가**가 물음입니다. 판단이 안 서면 `grid-large.png` 로
확인하시되, 답은 작은 쪽 기준으로 적어 주세요.

화풍마다 **가장 헷갈리는 다른 화풍의 번호 하나**를 적어 주세요. 헷갈리는 것이 없으면
비워 두시면 됩니다. 짝을 다 묻지 않고 이렇게 묻는 이유는 {count}종이면 짝이 28개라
채우다 지치기 때문입니다 - 두 분이 서로를 지목하면 그것이 곧 닮은 짝입니다.

| # | 화풍 | 가장 헷갈리는 번호 | 왜 (한 줄) |
|---|---|---|---|
{confuse}

**격자 전체를 놓고 느낀 것**을 자유롭게 적어 주세요. 위 표에 안 들어가는 것이면 무엇이든
좋습니다 (예: "전체적으로 톤이 비슷하다", "하나만 유독 튄다").

답:

---

## 2절. 이름이 화풍을 가리킵니까

2026-08-22 판정의 자유 응답에서 **2번과 6번은 이름만으로 어떤 화풍인지 알기 어렵다**는
지적이 나왔습니다. 화면에 그대로 뜨는 이름이라 사용자도 같은 어려움을 겪습니다.

**다만 8종 목록은 A-3 이 확정한 값이라 소관자가 고칠 수 없습니다.** 이 양식은 결정이
아니라 **회의 안건에 올릴 준비물**입니다.

각 화풍에 대해, **그림을 보지 않고 이름만 보았을 때** 어떤 그림일지 떠오르는지 적어
주세요. 안 떠오르면 대안 이름을 제안해 주시면 좋습니다.

| # | 현재 이름 | 이름만으로 떠오름 (Y/N) | 대안 제안 (있으면) |
|---|---|---|---|
{naming}

### 바꾸기로 하면 대가가 두 갈래로 갈립니다

답을 적으실 때 참고만 하세요. 어느 쪽인지 정하는 것은 회의입니다.

| 갈래 | 무엇이 바뀌나 | 대가 |
|---|---|---|
| 화면 표기(`name`)만 | 사용자에게 보이는 글자만 | **없음.** 예시 이미지는 그대로 씁니다 |
| 프롬프트 값(`artStyleId`)까지 | 생성에 실리는 문자열 | **그 화풍의 예시를 다시 만들어야 하고, 나온 그림이 지금과 달라질 수 있습니다** (요금 발생) |

두 값이 갈라져 있는 것은 계약의 설계입니다. 즉 **이름만 바꾸는 것은 공짜이고**, 그림까지
바꾸려는 것이면 재생성이 따라옵니다.

---

## 3절. C4 진행에 대한 회고

판정 자체가 아니라 **진행 방식**에 대한 의견입니다. 다음 검증(5순위)에 바로 반영합니다.

| 물음 | 답 |
|---|---|
| 시트를 채우기 어렵지 않았습니까 (분량, 표현, 파일 열기) |  |
| A/B 를 가린 것이 도움이 됐습니까, 아니면 답답했습니까 |  |
| 결과를 나중에 보셨을 때 "내가 답한 것이 이렇게 쓰였구나" 가 보였습니까 |  |
| 다음 검증에서 바꿨으면 하는 것 |  |

**하고 싶은 말 아무거나** (수행자가 놓치고 있는 것이 있다면 특히):

답:
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="C4 의견 수렴 배치 조립")
    parser.add_argument("--judges", nargs="*", default=list(JUDGES))
    args = parser.parse_args()

    cells = _cells()
    OPINION.mkdir(parents=True, exist_ok=True)

    actual = OPINION / "grid-actual.png"
    large = OPINION / "grid-large.png"
    _contact_sheet(cells, CARD_PX, CARD_GAP, badge=False).save(actual)
    _contact_sheet(cells, LARGE_PX, LARGE_GAP, badge=True).save(large)

    roster = "\n".join(f"| {style.index} | {style.name} |" for style, _ in cells)
    confuse = "\n".join(f"| {style.index} | {style.name} |  |  |" for style, _ in cells)
    naming = "\n".join(f"| {style.index} | {style.name} |  |  |" for style, _ in cells)

    for judge in args.judges:
        path = OPINION / f"opinion-{judge}.md"
        path.write_text(
            HEADER.format(
                judge=judge,
                card=CARD_PX,
                large=LARGE_PX,
                count=len(cells),
                roster=roster,
                confuse=confuse,
                naming=naming,
            ),
            encoding="utf-8",
        )
        print(f"생성: {path.name}")

    print(f"\n배치: {OPINION}")
    print(f"  {actual.name} - 실제 화면 크기 (카드 {CARD_PX}px). 100% 배율로 보게 안내하세요")
    print(f"  {large.name} - 참조용 {LARGE_PX}px, 번호 표시")
    print(
        "\n⚠️ 1절은 **1번과 2번을 지목하지 않습니다.** 그 짝이 닮았는지가 확인하려는 것이라, "
        "물음에 넣으면 원하는 답이 나옵니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

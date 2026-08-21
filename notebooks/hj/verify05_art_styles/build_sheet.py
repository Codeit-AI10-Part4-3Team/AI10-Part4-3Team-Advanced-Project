"""화풍 예시 채택 판정 배치를 조립합니다 (C4).

    python build_sheet.py                       # 배치 폴더 + 시트 3벌
    python build_sheet.py --judges 정승호 임동규

⚠️ **판정은 03 을 제외한 전원이 합니다.** 수행자가 자기 결과를 채점하면 교차 검증이 형식만
남습니다(구현_범위 4.4절). 제가 16장을 보고 내린 "특징 포함이 낫다" 는 **의견이지 판정이
아닙니다** - 그것을 확인받으려고 이 시트를 만듭니다.

**A/B 를 가립니다.** 어느 쪽이 이름만이고 어느 쪽이 특징까지 넣은 것인지 알려 주지 않고
`가` / `나` 로만 보여 줍니다. 알고 보면 "정보를 더 준 쪽이 낫겠지" 라는 쪽으로 판정이
기웁니다. 좌우 배치도 화풍마다 뒤집습니다 - 한쪽으로 몰아 두면 세 번째 화풍쯤에서
판정자가 규칙을 눈치챕니다.

화풍 **이름은 가리지 않습니다.** 이 판정의 핵심 물음이 "그림이 이 이름을 대표하는가" 라
이름을 숨기면 물어볼 것이 없어집니다. 3순위에서 조건표를 가린 것과는 사정이 다릅니다.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
from pathlib import Path

import styles

SOURCE = Path(__file__).resolve().parents[3] / "outputs" / "API_이미지생성_검증" / "화풍_8종_예시"
BATCH = SOURCE / "판정_배치"
SEED = 20260821
"""좌우 배치를 섞는 시드. 고정해 두어야 대응표를 잃어도 다시 만들 수 있습니다."""

JUDGES = ("정승호", "임동규", "송기하")

HEADER = """# 화풍 예시 채택 판정 - 화풍 8종 / {judge}

## 무엇을 보는가

화풍 후보 8종의 **예시 이미지**를 고릅니다. 이 그림은 사용자가 광고를 만들기 전에 화풍을
고르는 화면(4 x 2 격자)에 걸립니다. 즉 **사용자가 이것을 보고 기대를 세우고, 실제 결과가
그 기대와 같아야 합니다.**

화풍마다 후보가 두 장 있습니다. `가` 와 `나` 이고 **어느 쪽이 무엇인지는 알려 드리지
않습니다.** 알고 보면 판정이 한쪽으로 기웁니다.

한 화풍씩 두 장을 나란히 놓고 세 가지를 답해 주세요.

1. **이름에 맞는 쪽** - "심플 플랫 웹툰" 이라는 이름을 보고 떠올린 그림에 더 가까운 쪽.
   `가` / `나` / `둘 다` / `둘 다 아님` 중 하나입니다.
2. **화면에 걸 수 있는가** - 고른 쪽을 그대로 선택 화면에 써도 되는지. 그림이 이상하거나
   (손, 사물의 물리) 광고 예시로 부적절하면 `N` 입니다.
3. **메모** - `둘 다 아님` 이나 `N` 을 적었으면 **왜인지 한 줄** 적어 주세요. 이유가 없으면
   다시 만들 때 무엇을 고쳐야 할지 알 수 없습니다.

## 어떻게 채우는가

- **`이름에 맞는 쪽` 열이 이 판정의 본체입니다.** 비우면 그 화풍은 집계에서 통째로 빠집니다.
- **`화면에 걸 수 있는가` 도 반드시 채워 주세요.** 이름에는 맞는데 그림이 망가진 경우가
  따로 있습니다. 두 열은 다른 질문입니다.
- 판단이 서지 않는 화풍만 비우고 메모에 이유를 적으세요. 추측으로 채운 값이 근거로
  올라가는 것보다 낫습니다.
- **회차끼리 비교하지 마세요.** 8종은 서로 달라야 하는 것이 정상입니다. 다만 마지막
  물음에서 한 번 전체를 봅니다.

## 채점

| # | 화풍 | 이미지 | 이름에 맞는 쪽 (가/나/둘 다/둘 다 아님) | 화면에 걸 수 있는가 (Y/N) | 메모 |
|---|---|---|---|---|---|
"""

FOOTER = """
## 전체를 놓고 (마지막 물음)

8종을 한 화면에 놓고 보았을 때 **서로 구분됩니까?** 구분이 안 되는 짝이 있으면 번호를
적어 주세요 (예: `1 과 2 가 비슷함`).

답:

## 총평 (한 줄)

"""


def _pairs() -> list[tuple[styles.ArtStyle, str, str]]:
    """화풍마다 (가, 나) 에 어느 파일을 놓을지. 시드가 고정이라 재현됩니다.

    ⚠️ **동전 던지기가 아니라 4 대 4 를 섞습니다.** 화풍마다 독립으로 뒤집으면 8번에
    6 대 2 처럼 치우치는 일이 실제로 나오고(첫 조립에서 그랬습니다), 그러면 판정자가
    "가 가 대체로 이쪽이네" 를 눈치챕니다. 가리는 것이 목적이므로 균형을 강제합니다.
    """
    rng = random.Random(SEED)
    half = len(styles.ART_STYLES) // 2
    plain_first = [True] * half + [False] * (len(styles.ART_STYLES) - half)
    rng.shuffle(plain_first)
    result = []
    for style, plain_on_left in zip(styles.ART_STYLES, plain_first, strict=True):
        plain, traits = f"{style.slug}.png", f"{style.slug}-traits.png"
        result.append((style, plain, traits) if plain_on_left else (style, traits, plain))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="화풍 예시 채택 판정 배치 조립 (C4)")
    parser.add_argument("--judges", nargs="*", default=list(JUDGES))
    args = parser.parse_args()

    missing = [
        name
        for style in styles.ART_STYLES
        for name in (f"{style.slug}.png", f"{style.slug}-traits.png")
        if not (SOURCE / name).exists()
    ]
    if missing:
        raise SystemExit(f"생성되지 않은 이미지가 있습니다: {missing[:4]} ...")

    BATCH.mkdir(parents=True, exist_ok=True)
    pairs = _pairs()
    key_rows = []

    for style, first, second in pairs:
        for label, source_name in (("가", first), ("나", second)):
            target = BATCH / f"{style.slug}-{label}.png"
            shutil.copyfile(SOURCE / source_name, target)
            key_rows.append(
                {
                    "index": style.index,
                    "name": style.name,
                    "label": label,
                    "condition": "특징 포함" if source_name.endswith("-traits.png") else "이름만",
                    "source": source_name,
                }
            )

    with (BATCH / "_대응표.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["index", "name", "label", "condition", "source"]
        )
        writer.writeheader()
        writer.writerows(key_rows)

    for judge in args.judges:
        lines = [HEADER.format(judge=judge)]
        for style, _, _ in pairs:
            lines.append(
                f"| {style.index} | {style.name} | `{style.slug}-가.png` / "
                f"`{style.slug}-나.png` |  |  |  |\n"
            )
        lines.append(FOOTER)
        path = BATCH / f"art-style-{judge}.md"
        path.write_text("".join(lines), encoding="utf-8")
        print(f"생성: {path.name}")

    print(
        f"\n배치: {BATCH}\n"
        "이미지 16장(화풍 8종 x 가/나)과 시트 3벌입니다. "
        "**`_대응표.csv` 는 판정자에게 주지 마세요** - 어느 쪽이 어떤 조건인지 적혀 있습니다.\n"
        "회수 후 `python tally_sheet.py` 로 집계합니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""회수한 화풍 예시 판정 시트를 집계합니다 (C4).

    python tally_sheet.py

⚠️ **판정자 수로 표본을 곱하지 않습니다.** 세 사람이 같은 이미지를 보는 것이라 독립 표본이
아닙니다. 화풍 단위로 접고 **다수결(3명 중 2명 이상)** 로 판정합니다 - 3순위에서 쓴 규칙과
같습니다(B-16).

⚠️ **`둘 다 아님` 은 `가` 도 `나` 도 아닙니다.** 다수결에서 빼지 말고 따로 세어야 합니다.
그 화풍은 예시를 **다시 만들어야 하는** 것이지 어느 쪽이 낫다는 답이 아닙니다.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import styles
from build_sheet import BATCH

CHOICES = ("가", "나", "둘 다", "둘 다 아님")


def _read_key() -> dict[tuple[int, str], str]:
    """(화풍 번호, 가/나) -> 조건. 판정이 끝난 뒤에 엽니다."""
    path = BATCH / "_대응표.csv"
    if not path.exists():
        raise SystemExit("_대응표.csv 가 없습니다. build_sheet.py 를 먼저 돌리세요.")
    with path.open(encoding="utf-8") as handle:
        return {(int(r["index"]), r["label"]): r["condition"] for r in csv.DictReader(handle)}


def _parse(path: Path) -> dict[int, tuple[str, str, str]]:
    """시트에서 (화풍 번호 -> (선택, 게시 가능, 메모))."""
    result: dict[int, tuple[str, str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        result[int(cells[0])] = (cells[3], cells[4].upper(), cells[5])
    return result


def main() -> int:
    sheets = sorted(BATCH.glob("art-style-*.md"))
    if not sheets:
        raise SystemExit("회수한 시트가 없습니다.")
    key = _read_key()
    filled = {sheet.stem[len("art-style-") :]: _parse(sheet) for sheet in sheets}

    print(f"판정자 {len(sheets)}명: {', '.join(filled)}\n")
    print("| # | 화풍 | 선택 (다수결) | 그 선택의 조건 | 게시 가능 | 갈린 표 |")
    print("|---|---|---|---|---|---|")

    adopt: Counter[str] = Counter()
    redo: list[int] = []

    for style in styles.ART_STYLES:
        votes = [v[0] for v in (f.get(style.index, ("", "", "")) for f in filled.values()) if v[0]]
        posts = [v[1] for v in (f.get(style.index, ("", "", "")) for f in filled.values()) if v[1]]
        if not votes:
            print(f"| {style.index} | {style.name} | 판정 없음 | -- | -- | -- |")
            continue
        counted = Counter(votes)
        top, count = counted.most_common(1)[0]
        # 과반이어야 판정입니다. 3명이 전부 다르게 답하면 다수결이 성립하지 않습니다.
        decided = top if count * 2 > len(votes) else "갈림"
        condition = key.get((style.index, top), "--") if decided in ("가", "나") else "--"
        if decided in ("가", "나"):
            adopt[condition] += 1
        elif decided == "둘 다 아님":
            redo.append(style.index)
        ok = sum(1 for p in posts if p == "Y")
        split = "" if count == len(votes) else f"{dict(counted)}"
        print(
            f"| {style.index} | {style.name} | {decided} | {condition} | "
            f"{ok}/{len(posts)} | {split} |"
        )

    print(
        f"\n채택된 조건: {dict(adopt) or '없음'}. "
        "**이 숫자가 `artStyleId` 에 특징을 실을지를 정합니다** - 한쪽으로 몰리면 그쪽입니다."
    )
    if redo:
        print(f"다시 만들어야 하는 화풍: {redo} (둘 다 아님 다수결)")
    print(
        "\n마지막 물음('서로 구분됩니까')의 답은 자동 집계하지 않습니다. "
        "구분이 안 되는 짝은 검증 5순위(C3)의 입력이라 시트를 눈으로 읽으세요.\n"
        "수치는 RESULTS.md 에 옮기세요. 배치는 outputs/ 라 커밋되지 않습니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

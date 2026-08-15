"""블라인드 판정 시트 생성과 집계.

기획서 15절: 결과물을 만든 사람이 자기 결과물을 채점하지 않습니다. 이 스크립트는 실험을 돌린
사람이 아닌 판정자에게 넘길 시트를 만들고, 채워진 시트를 B-16 기준으로 집계합니다.

    python score_sheet.py build --run-dir runs/20260813-2010-main --judges 정승호 임동규 송기하
    python score_sheet.py tally --run-dir runs/20260813-2010-main

`build`가 만드는 시트에는 프롬프트도 조건도 들어가지 않습니다. 판정자가 "무엇이 나와야 하는지"를
먼저 읽으면 없는 글자를 있다고 읽습니다 - 정답 대사는 시트에 들어가지만 어느 쪽이 본안이고
예비안인지는 파일 이름 밖으로 드러내지 않습니다.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import conditions

SHEET_PREFIX = "sheet"

# ⚠️ 3순위 시트를 같은 이름으로 쓰면 **이미 채워진 1순위 판정을 덮어씁니다.** 같은 회차
# 폴더를 다시 쓰는 설계라(3순위는 1순위 이미지를 그대로 봅니다) 이름을 갈라 두어야 합니다.
TASK_PREFIX = {"text": SHEET_PREFIX, "consistency": "consistency"}


def _read_manifest(run_dir: Path) -> list[dict[str, str]]:
    manifest = run_dir / "manifest.csv"
    if not manifest.exists():
        raise SystemExit(f"{manifest}가 없습니다. run_experiment.py를 먼저 돌리세요.")
    with manifest.open(encoding="utf-8") as fp:
        rows = [row for row in csv.DictReader(fp) if row.get("image_file")]
    if not rows:
        raise SystemExit("성공한 회차가 없습니다. manifest.csv의 error 열을 보세요.")
    return rows


def _variant_of(run_dir: Path, rows: list[dict[str, str]]) -> str:
    return rows[0].get("variant") or run_dir.name.rsplit("-", 1)[-1]


def _build(run_dir: Path, judges: list[str], task: str = "text") -> None:
    rows = _read_manifest(run_dir)
    variant = _variant_of(run_dir, rows)

    if task == "consistency":
        # 검증 3순위. 1순위에서 만든 이미지를 그대로 다시 봅니다 - 같은 조건에서 나온 그림이라
        # 새로 생성할 이유가 없고, 생성하면 조건이 달라져 1순위 결과와 이어 붙일 수 없습니다.
        criterion = (
            "**한 장 안에서** 두 가지를 봅니다. 회차끼리 비교하지 마세요.\n\n"
            "1. **같은 인물인가** - 1번부터 5번 칸에 나오는 사람이 같은 사람으로 보이는지. "
            "얼굴, 머리 모양, 복장이 기준입니다. 6번 칸은 제품 컷이라 제외합니다.\n"
            "2. **화풍이 일관되는가** - 6칸이 같은 그림체인지. 한 칸만 사진처럼 나오거나 "
            "다른 톤이면 실패입니다.\n"
        )
        count_column = "동일 인물 (1) / 아님 (0)"
        count_hint = "1번부터 5번 칸이 같은 사람으로 보이면 `1`, 아니면 `0`"
        columns = ["회차", "이미지 파일", count_column, "6칸 화풍 일관 (Y/N)", "메모"]
    elif variant == "single":
        # 단일 광고형은 칸이 없습니다. 6칸 척도를 그대로 쓰면 판정자가 없는 칸을 세게 됩니다.
        criterion = (
            "이미지에 그려진 한국어 카피가 아래 정답과 **글자 단위로 완전히 같은지** 봅니다. "
            "한 글자라도 다르거나, 빠지거나, 깨져 있으면 실패입니다. 정답에 없는 문구가 이미지에 "
            "추가로 그려져 있어도 실패입니다 (근거에 없는 문구를 넣지 말라고 지시했습니다).\n\n"
            f"- 카피: `{conditions.SINGLE_AD_COPY}`\n"
        )
        count_column = "카피 정확 (1) / 실패 (0)"
        count_hint = "정확하면 `1`, 한 글자라도 어긋나거나 없는 문구가 추가됐으면 `0`"
        columns = ["회차", "이미지 파일", count_column, "제품이 주인공 (Y/N)", "메모"]
    elif variant in ("main", "hard"):
        # 어려운 대사 회차는 정답 문자열만 다르고 척도는 같습니다. 정답 표를 갈아 끼우지
        # 않으면 판정자가 1순위 대사를 기준으로 채점하게 됩니다.
        panels = conditions.PANELS_HARD if variant == "hard" else conditions.PANELS
        answer_block = "\n".join(f"- {p.index}번 칸: `{p.line}`" for p in panels)
        criterion = (
            "각 칸의 말풍선 글자가 아래 정답과 **글자 단위로 완전히 같은지** 봅니다. "
            "한 글자라도 다르거나, 빠지거나, 깨져 있으면 그 칸은 오탈자입니다.\n\n"
            f"{answer_block}\n"
        )
        count_column = "오탈자 없는 칸 수 (0-6)"
        count_hint = "여섯 칸 모두 정확하면 `6`, 한 칸만 틀렸으면 `5`"
        columns = ["회차", "이미지 파일", count_column, "6칸 균등 분할 (Y/N)", "메모"]
    else:
        criterion = (
            "각 칸에 말풍선이 있고 그 안이 **비어 있는지** 봅니다. 글자처럼 보이는 것이 하나라도 "
            "그려져 있으면 그 칸은 실패입니다 (예비안은 글자를 나중에 합성합니다).\n"
        )
        count_column = "빈 말풍선 칸 수 (0-6)"
        count_hint = "여섯 칸 모두 비어 있으면 `6`, 한 칸에 글자가 보이면 `5`"
        columns = ["회차", "이미지 파일", count_column, "6칸 균등 분할 (Y/N)", "메모"]

    # ⚠️ 이 안내가 없던 1차 회차에서 판정자 한 명이 세 번째 열을 통째로 비워, 그분의 판정이
    # 집계에서 빠졌습니다(총평에는 결론이 적혀 있었는데도). 열의 의미를 시트 안에서 못 읽으면
    # 메모만 채우게 됩니다.
    how_to_fill = (
        "## 어떻게 채우는가\n\n"
        f"- **`{count_column}` 열이 이 판정의 본체입니다.** 숫자를 적으세요 - "
        f"{count_hint}.\n"
        "- **이 열이 비면 그 회차는 집계에서 통째로 빠집니다.** 총평에 결론을 적어도 수치로는 "
        "들어가지 않습니다.\n"
        "- 판단이 서지 않는 회차만 비우고 메모에 이유를 적으세요. 추측으로 채운 값이 근거로 "
        "올라가는 것보다는 낫습니다.\n"
        f"- 나머지 두 열({columns[3]}, 메모)은 참고용입니다. 비어 있어도 판정은 성립합니다."
    )

    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"

    for judge in judges:
        lines = [
            f"# 판정 시트 - {run_dir.name} / {judge}",
            "",
            "## 무엇을 보는가",
            "",
            criterion,
            "**이미지를 만든 사람은 이 시트를 채우지 않습니다.**",
            "",
            how_to_fill,
            "",
            "## 채점",
            "",
            header,
            divider,
        ]
        for row in rows:
            lines.append(f"| {row['run_id']} | `{row['image_file']}` |  |  |  |")
        lines += [
            "",
            "## 총평 (한 줄)",
            "",
            "",
        ]
        path = run_dir / f"{TASK_PREFIX[task]}-{judge}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"생성: {path}")

    print(
        "\n판정자에게 시트와 이미지를 함께 넘기세요. 이미지는 커밋하지 말고 팀 공유 드라이브로 "
        "올립니다 (구현_범위 4.3절)."
    )


def _parse_sheet(path: Path) -> dict[int, tuple[int | None, str | None]]:
    """채워진 시트에서 (회차 -> (칸 수, 균등 분할))만 뽑습니다."""
    result: dict[int, tuple[int | None, str | None]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        panels = int(cells[2]) if cells[2].isdigit() else None
        grid = cells[3].upper() if cells[3] else None
        result[int(cells[0])] = (panels, grid)
    return result


def _tally(run_dir: Path, task: str = "text") -> None:
    rows = _read_manifest(run_dir)
    variant = _variant_of(run_dir, rows)
    prefix = TASK_PREFIX[task]
    sheets = sorted(run_dir.glob(f"{prefix}-*.md"))
    if not sheets:
        raise SystemExit("채워진 판정 시트가 없습니다. build를 먼저 돌리고 판정을 받으세요.")

    total = len(rows)
    print(f"회차 {total}건 / 판정자 {len(sheets)}명 / variant={variant}\n")

    # 단일 광고형은 칸이 없어 척도가 0/1 입니다. 6칸 기준을 그대로 적용하면 정확한 회차가
    # 전부 실패로 집계됩니다.
    if task == "consistency":
        threshold, scale, side_label = 1, "동일 인물 판정", "6칸 화풍 일관"
    elif variant == "single":
        threshold, scale, side_label = 1, "카피 정확", "제품이 주인공"
    else:
        threshold = conditions.PANELS_OK_THRESHOLD
        scale = f"{conditions.PANELS_OK_THRESHOLD}칸 이상"
        side_label = "6칸 균등 분할"

    for sheet in sheets:
        judge = sheet.stem[len(prefix) + 1 :]
        scored = _parse_sheet(sheet)
        filled = {k: v for k, v in scored.items() if v[0] is not None}
        if not filled:
            print(f"- {judge}: 채워진 칸이 없습니다 (건너뜀)")
            continue

        ok_runs = sum(1 for panels, _ in filled.values() if panels >= threshold)
        rate = ok_runs / len(filled)
        side_ok = sum(1 for _, grid in filled.values() if grid == "Y")
        side_rate = side_ok / len(filled)

        print(f"- {judge}: 판정 {len(filled)}/{total}건")
        print(
            f"    성공 판정 - {scale} {ok_runs}건 "
            f"= {rate:.0%} (기준 {conditions.PASS_RATE_THRESHOLD:.0%})"
        )
        print(f"    참고 - {side_label} {side_ok}건 = {side_rate:.0%}")
        if len(filled) < conditions.TARGET_RUNS:
            print(f"    주의: 회차가 {conditions.TARGET_RUNS}회에 못 미쳐 확정 판정이 아닙니다")
        else:
            verdict = "기준 충족" if rate >= conditions.PASS_RATE_THRESHOLD else "기준 미달"
            print(f"    판정: {verdict}")

    print(
        "\n수치는 회의록과 미결정_대장(A-1)에 옮기세요. 시트와 이미지는 커밋되지 않으므로 "
        "여기에만 두면 없었던 실험이 됩니다 (구현_범위 4.3절)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="판정 시트 생성")
    build.add_argument("--run-dir", type=Path, required=True)
    build.add_argument("--judges", nargs="+", required=True, help="실험을 돌린 사람은 제외")
    build.add_argument(
        "--task",
        choices=["text", "consistency"],
        default="text",
        help="text=대사 표기(1순위), consistency=캐릭터와 화풍 일관성(3순위). "
        "3순위는 1순위 이미지를 그대로 다시 보므로 추가 생성이 없습니다",
    )

    tally = sub.add_parser("tally", help="채워진 시트 집계")
    tally.add_argument("--run-dir", type=Path, required=True)
    tally.add_argument("--task", choices=["text", "consistency"], default="text")

    args = parser.parse_args()
    if args.command == "build":
        _build(args.run_dir, args.judges, args.task)
    else:
        _tally(args.run_dir, args.task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

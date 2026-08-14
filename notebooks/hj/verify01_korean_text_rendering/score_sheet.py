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


def _build(run_dir: Path, judges: list[str]) -> None:
    rows = _read_manifest(run_dir)
    variant = _variant_of(run_dir, rows)

    if variant == "main":
        answer_block = "\n".join(
            f"- {p.index}번 칸: `{p.line}`" for p in conditions.PANELS
        )
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
        "- 나머지 두 열(균등 분할, 메모)은 참고용입니다. 비어 있어도 판정은 성립합니다."
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
        path = run_dir / f"{SHEET_PREFIX}-{judge}.md"
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


def _tally(run_dir: Path) -> None:
    rows = _read_manifest(run_dir)
    variant = _variant_of(run_dir, rows)
    sheets = sorted(run_dir.glob(f"{SHEET_PREFIX}-*.md"))
    if not sheets:
        raise SystemExit("채워진 판정 시트가 없습니다. build를 먼저 돌리고 판정을 받으세요.")

    total = len(rows)
    print(f"회차 {total}건 / 판정자 {len(sheets)}명 / variant={variant}\n")

    for sheet in sheets:
        judge = sheet.stem[len(SHEET_PREFIX) + 1 :]
        scored = _parse_sheet(sheet)
        filled = {k: v for k, v in scored.items() if v[0] is not None}
        if not filled:
            print(f"- {judge}: 채워진 칸이 없습니다 (건너뜀)")
            continue

        ok_runs = sum(1 for panels, _ in filled.values() if panels >= conditions.PANELS_OK_THRESHOLD)
        rate = ok_runs / len(filled)
        grid_ok = sum(1 for _, grid in filled.values() if grid == "Y")
        grid_rate = grid_ok / len(filled)

        print(f"- {judge}: 판정 {len(filled)}/{total}건")
        print(
            f"    1순위 - {conditions.PANELS_OK_THRESHOLD}칸 이상 성공 {ok_runs}건 "
            f"= {rate:.0%} (기준 {conditions.PASS_RATE_THRESHOLD:.0%})"
        )
        print(f"    2순위 참고 - 6칸 균등 분할 {grid_ok}건 = {grid_rate:.0%} (실패율 {1 - grid_rate:.0%})")
        if len(filled) < conditions.TARGET_RUNS:
            print(f"    주의: 회차가 {conditions.TARGET_RUNS}회에 못 미쳐 확정 판정이 아닙니다")
        else:
            verdict = "본안 유지" if rate >= conditions.PASS_RATE_THRESHOLD else "예비안 전환 검토"
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

    tally = sub.add_parser("tally", help="채워진 시트 집계")
    tally.add_argument("--run-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "build":
        _build(args.run_dir, args.judges)
    else:
        _tally(args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

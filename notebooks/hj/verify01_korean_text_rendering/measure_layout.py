"""검증 2순위 - 컷 경계를 사람 눈이 아니라 픽셀로 잽니다.

1순위 판정에서 두 판정자가 독립적으로 "이미지 **간** 여백 사이즈가 미세하게 다르다"고
지적했습니다. 판정 시트는 "같은 이미지 안에서 6칸이 균등한가"만 물었고 거기서는 30건 전부
통과했으므로, Y/N 판정으로는 이 문제가 잡히지 않습니다.

측정 대상을 바꿉니다:

- 한 장 안의 균등함 -> 칸 폭/높이의 최대 편차 (px)
- **장과 장 사이** -> 바깥 여백과 칸 크기가 회차마다 얼마나 흔들리는가 (px)

두 번째가 실제로 걸리는 성질입니다. 여백이 회차마다 다르면 인스타그램 그리드나 캐러셀로
자를 때 **고정 좌표 크롭이 성립하지 않습니다.**

    python measure_layout.py --run-dir runs/20260813-225333-main

⚠️ 이 스크립트는 API 를 호출하지 않습니다. 이미 만든 이미지를 다시 읽을 뿐이라 비용이 0입니다.
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

import conditions

# 칸 사이 경계는 흰색 띠입니다 (프롬프트가 그렇게 지시합니다). 245는 JPEG 아닌 PNG 기준으로
# 순백과 아주 밝은 회색을 함께 잡는 값이고, 0.98은 그 줄에 그림이 조금 삐져나와도 경계로
# 인정하는 여유입니다. 둘 다 임계값이므로 결과를 읽을 때 함께 봐야 합니다.
WHITE_LEVEL = 245
WHITE_RATIO = 0.98

# 이보다 얇은 간격은 칸이 아니라 쪼개진 경계선입니다. 규격 칸이 1152px 이므로 100px 은
# 실제 칸을 삼킬 위험 없이 잡음만 걸러 냅니다.
MIN_CELL = 100


class Bands(NamedTuple):
    """한 축에서 찾은 흰 띠들. (시작, 끝) 쌍이며 끝은 포함하지 않습니다."""

    spans: list[tuple[int, int]]
    length: int

    def leading(self) -> int:
        """바깥 여백 (0에서 시작하는 띠의 두께). 없으면 0."""
        return self.spans[0][1] if self.spans and self.spans[0][0] == 0 else 0

    def trailing(self) -> int:
        last = self.spans[-1] if self.spans else None
        return self.length - last[0] if last and last[1] == self.length else 0

    def inner(self) -> list[tuple[int, int]]:
        """안쪽 경계만 (바깥 여백 제외)."""
        return [s for s in self.spans if s[0] != 0 and s[1] != self.length]

    def cells(self) -> list[int]:
        """띠 **사이**에 남은 칸들의 크기.

        띠의 두께가 아니라 띠와 띠 사이의 간격입니다. 두 개를 헷갈리면 칸 폭 1152px 대신
        경계 두께 25px 가 칸으로 보고됩니다.
        """
        sizes: list[int] = []
        cursor = 0
        for start, end in self.spans:
            if start > cursor:
                sizes.append(start - cursor)
            cursor = end
        if cursor < self.length:
            sizes.append(self.length - cursor)
        return sizes


def _find_bands(white_ratio: np.ndarray) -> list[tuple[int, int]]:
    """비율이 임계값 이상인 구간을 (시작, 끝)으로 묶습니다."""
    mask = white_ratio >= WHITE_RATIO
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            spans.append((start, index))
            start = None
    if start is not None:
        spans.append((start, len(mask)))
    # 1 ~ 2px 짜리 잡음은 경계가 아니라 안티에일리어싱입니다.
    spans = [(a, b) for a, b in spans if b - a >= 3]

    # 경계선 한가운데에 밝지 않은 화소가 몇 줄 끼면 띠가 둘로 쪼개지고, 그 사이의 5px 짜리
    # 틈이 "칸"으로 세어집니다(실측: main-07). 칸이라기에 터무니없이 얇은 간격은 경계의
    # 일부로 되돌립니다.
    merged: list[tuple[int, int]] = []
    for span in spans:
        if merged and span[0] - merged[-1][1] < MIN_CELL:
            merged[-1] = (merged[-1][0], span[1])
        else:
            merged.append(span)
    return merged


def measure(path: Path) -> dict[str, object]:
    with Image.open(path) as img:
        gray = np.asarray(img.convert("L"))

    is_white = gray >= WHITE_LEVEL
    cols = Bands(_find_bands(is_white.mean(axis=0)), gray.shape[1])
    rows = Bands(_find_bands(is_white.mean(axis=1)), gray.shape[0])

    return {
        "file": path.name,
        "size": (gray.shape[1], gray.shape[0]),
        "margin_left": cols.leading(),
        "margin_right": cols.trailing(),
        "margin_top": rows.leading(),
        "margin_bottom": rows.trailing(),
        "gutters_x": [b - a for a, b in cols.inner()],
        "gutters_y": [b - a for a, b in rows.inner()],
        "panel_widths": cols.cells(),
        "panel_heights": rows.cells(),
    }


def _spread(values: list[float]) -> str:
    if not values:
        return "-"
    if len(values) == 1:
        return f"{values[0]:.0f}"
    return f"{min(values):.0f} ~ {max(values):.0f} (편차 {max(values) - min(values):.0f})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--glob", default="*.png")
    args = parser.parse_args()

    paths = sorted(p for p in args.run_dir.glob(args.glob) if not p.name.startswith("_"))
    if not paths:
        raise SystemExit(f"{args.run_dir}에 이미지가 없습니다.")

    results = [measure(p) for p in paths]

    print(f"# {args.run_dir.name} - {len(results)}장\n")
    print("## 한 장 안의 균등함 (칸 크기의 최대 편차)\n")
    print("| 파일 | 칸 폭 | 폭 편차 | 칸 높이 | 높이 편차 | 바깥 여백 (좌/우/상/하) |")
    print("|---|---|---|---|---|---|")

    within_w: list[int] = []
    within_h: list[int] = []
    for r in results:
        widths = r["panel_widths"]  # type: ignore[assignment]
        heights = r["panel_heights"]  # type: ignore[assignment]
        dw = max(widths) - min(widths) if widths else 0
        dh = max(heights) - min(heights) if heights else 0
        within_w.append(dw)
        within_h.append(dh)
        margins = (r["margin_left"], r["margin_right"], r["margin_top"], r["margin_bottom"])
        print(
            f"| `{r['file']}` | {len(widths)}칸 {min(widths) if widths else 0}"
            f" ~ {max(widths) if widths else 0} | **{dw}** |"
            f" {len(heights)}칸 {min(heights) if heights else 0}"
            f" ~ {max(heights) if heights else 0} | **{dh}** |"
            f" {'/'.join(str(m) for m in margins)} |"
        )

    def col(key: str) -> list[float]:
        return [float(r[key]) for r in results]  # type: ignore[arg-type]

    all_widths = [w for r in results for w in r["panel_widths"]]  # type: ignore[misc]
    all_heights = [h for r in results for h in r["panel_heights"]]  # type: ignore[misc]

    print("\n## 장과 장 사이의 편차 (고정 좌표 크롭이 성립하는가)\n")
    print("| 항목 | 값 | 표준편차 |")
    print("|---|---|---|")
    for label, values in (
        ("바깥 여백 좌", col("margin_left")),
        ("바깥 여백 우", col("margin_right")),
        ("바깥 여백 상", col("margin_top")),
        ("바깥 여백 하", col("margin_bottom")),
        ("칸 폭 (전체)", [float(v) for v in all_widths]),
        ("칸 높이 (전체)", [float(v) for v in all_heights]),
    ):
        sd = statistics.pstdev(values) if len(values) > 1 else 0.0
        print(f"| {label} | {_spread(values)} | {sd:.1f} |")

    print(
        f"\n- 규격값: 칸 {conditions.PANEL_WIDTH} x {conditions.PANEL_HEIGHT}, "
        f"캔버스 {conditions.CANVAS_WIDTH} x {conditions.CANVAS_HEIGHT}"
    )
    print(f"- 한 장 안 칸 폭 편차: 최대 {max(within_w)}px / 높이 편차: 최대 {max(within_h)}px")
    print(
        f"- 임계값: 흰색 {WHITE_LEVEL} 이상, 한 줄의 {WHITE_RATIO:.0%} 이상이 흰색이면 경계. "
        "임계값을 바꾸면 숫자가 바뀝니다"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

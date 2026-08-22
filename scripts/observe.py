#!/usr/bin/env python3
"""운영 로그에서 지연 p95, 실패율, 열화 비율을 셉니다 (05 일정 08-26).

`backend_core.observability` 가 남긴 `obs` 줄을 읽습니다. 로그는 컨테이너 표준 출력이 아니라
`adgen-state` 볼륨 아래 파일이며, 그 이유는 그 모듈의 docstring 에 있습니다.

    # VM 에서. 볼륨을 호스트에서 직접 읽습니다 (compose 프로젝트 이름이 `adgen` 으로
    # 고정돼 있어 볼륨 이름이 `adgen_adgen-state` 입니다).
    python3 scripts/observe.py --log-dir /var/lib/docker/volumes/adgen_adgen-state/_data/logs

    # 주의: 컨테이너 안에서 부를 수는 없습니다. backend 이미지의 빌드 컨텍스트가
    # apps/backend 이고 `pyproject.toml` 과 `src` 만 COPY 하므로 이 스크립트는 이미지에
    # 없습니다. 굳이 컨테이너에서 돌리려면 먼저 넣어야 합니다:
    #   docker compose -f infra/docker-compose.yml cp scripts/observe.py backend:/tmp/

    python3 scripts/observe.py --log-dir ./data/logs --since 2026-08-21

주의: **표본 수를 함께 읽으세요.** 이 스크립트는 회차가 세 건이어도 p95 를 계산합니다.
세 건에서 나온 p95 는 최댓값의 다른 이름이며, 보고서에 그대로 옮기면 근거가 되지 않습니다.

주의: **스텁으로 돌린 구간은 지표가 아닙니다** (AGENTS.md "현재 상태"). `ADGEN_GENERATION_MODE`
가 `stub` 인 동안 렌더는 외부를 부르지 않으므로 지연이 밀리초 단위로 나옵니다. 실물 회차와
섞이면 p95 가 조용히 낮아집니다 - 구간을 `--since` 로 잘라서 보세요.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE = re.compile(r"\bobs seam=(?P<seam>\S+) outcome=(?P<outcome>\S+) elapsed_ms=(?P<ms>\d+)")

# 어떤 결과를 실패로 셀 것인가. **이음매마다 다르고, 그 차이가 이 표의 전부입니다.**
#
# 주의: `refused` 와 `degraded` 를 실패에 넣지 마세요. 전자는 가드레일이 동작한 것이고
# (INV-6), 후자는 설계된 열화입니다 (ADR-0005). 실패로 세면 두 숫자가 한꺼번에 망가집니다 -
# 실패율은 정상 동작 때문에 올라가고, 정작 보고해야 할 거절률과 열화 비율은 셀 것이 없어집니다.
FAILURES: dict[str, set[str]] = {
    "image:render": {"failed", "unknown"},
    "draft:generate": {"timeout", "unavailable"},
    "draft:patch": {"timeout", "unavailable"},
    "brief:fill": set(),  # 이 이음매의 유일한 나쁜 결과가 degraded 이고, 그것은 실패가 아닙니다
}

# 주의: **여기 없는 이음매는 실패율을 0% 로 보고합니다.** 그것은 "건강하다" 가 아니라
# "무엇을 실패로 셀지 아무도 정하지 않았다" 입니다. 둘이 출력에서 구별되지 않으면 새 이음매를
# 배선하고 표에 넣는 것을 잊은 날 보고서가 조용히 거짓말을 합니다 - 아래에서 표시합니다.

# 실패는 아니지만 따로 세어 보고하는 결과. 05 일정 08-26 이 이름으로 요구한 것들입니다.
#
# 주의: **`needs_input` 은 두 가지가 섞인 숫자입니다** (B-11, 2026-08-22 부터). 세션 생성에서
# 나온 것은 이름 그대로 되물음이지만, 브리프 patch 의 재추론에서 나온 것은 **거기서 세션이
# 닫혔다는 뜻**입니다 - 재시도는 1회이고 그 1회가 판단 불능이면 `INSUFFICIENT_INPUT` 입니다.
# 이 표는 둘을 구별하지 못하고, `brief:fill` 의 실패 집합이 비어 있어(위 FAILURES) 종료가
# 실패율에도 잡히지 않습니다. 보고서에 "되물음 N%" 를 옮길 때 그 안에 종료가 섞여 있다는
# 것을 함께 적으세요.
#
# 새 outcome 을 만들지 않은 이유는 어휘가 아니라 표본입니다. `obs` 줄은 `_refill_brief` 안에서
# 나가는데 그 시점에는 닫을지 아직 모르고, 뒤에서 한 줄 더 쓰면 `brief:fill` 호출 수가 부풀어
# 지연 p95 의 표본이 오염됩니다. 종료를 따로 세려면 **별도 이음매**로 세는 편이 맞습니다
# (PR #204 리뷰, 신호정).
REPORTED: dict[str, str] = {
    "degraded": "열화",
    "degraded_photo_gone": "열화(사진 소실)",
    "refused": "가드레일 거절",
    "needs_input": "되물음(+ 브리프 patch 에서는 세션 종료)",
}


def percentile(values: list[int], q: float) -> int:
    """정렬 후 nearest-rank. 보간하지 않습니다.

    보간하면 **실제로 관측되지 않은 값**이 보고서에 들어갑니다. 표본이 수십 건인 구간에서
    그 차이는 작지만, "이 숫자는 실제 회차인가" 에 답할 수 있는 편이 낫습니다.
    """
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * q // 100))  # ceil
    return ordered[int(rank) - 1]


def read_lines(log_dir: Path, since: str | None) -> list[str]:
    """`app.log` 와 회전된 파일들을 함께 읽습니다.

    주의: 회전본을 빠뜨리면 **오늘치만 세고도 초록으로 끝납니다.** 하루 한 파일이므로
    어제 있었던 장애가 오늘 조회에서 사라집니다.
    """
    files = sorted(log_dir.glob("app.log*"))
    if not files:
        sys.exit(f"[중단] {log_dir} 에 app.log 가 없습니다. 경로와 볼륨 마운트를 확인하세요.")

    lines: list[str] = []
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if since and line[: len(since)] < since:
                continue
            lines.append(line)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path, default=Path("./data/logs"))
    parser.add_argument("--since", help="이 날짜 이후만 (YYYY-MM-DD). 로그 줄 앞머리와 비교합니다")
    args = parser.parse_args()

    latencies: dict[str, list[int]] = defaultdict(list)
    outcomes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for line in read_lines(args.log_dir, args.since):
        found = LINE.search(line)
        if found is None:
            continue
        seam = found["seam"]
        latencies[seam].append(int(found["ms"]))
        outcomes[seam][found["outcome"]] += 1

    if not latencies:
        print("obs 줄이 없습니다. 아직 아무 이음매도 돌지 않았거나, 로그가 갈렸습니다.")
        return 1

    for seam in sorted(latencies):
        samples = latencies[seam]
        counted = outcomes[seam]
        total = sum(counted.values())
        failures = sum(n for outcome, n in counted.items() if outcome in FAILURES.get(seam, set()))

        print(f"\n== {seam} ==")
        print(f"  표본            {total}건" + ("   <- 표본이 적습니다" if total < 20 else ""))
        print(f"  지연 p50 / p95  {percentile(samples, 50)} / {percentile(samples, 95)} ms")
        print(f"  최대            {max(samples)} ms")
        if seam in FAILURES:
            print(f"  실패율          {failures / total:.1%}  ({failures}/{total})")
        else:
            print("  실패율          ?  <- FAILURES 에 이 이음매가 없습니다 (0% 가 아닙니다)")
        for outcome, label in REPORTED.items():
            if outcome in counted:
                # 한글 라벨은 폭이 두 칸이라 문자 수로 맞추면 어긋납니다. 채우지 않습니다.
                share = counted[outcome] / total
                print(f"  {label}  {share:.1%}  ({counted[outcome]}/{total})")
        rest = ", ".join(f"{k}={v}" for k, v in sorted(counted.items()))
        print(f"  결과 분포       {rest}")

    print("\n주의: 표본 수를 함께 보고하세요. 스텁 구간이 섞이면 p95 가 낮아집니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

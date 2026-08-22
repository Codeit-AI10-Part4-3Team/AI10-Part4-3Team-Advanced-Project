"""검출기 단위 시험 - 위반 예문을 `check_claims` 에 직접 통과시킵니다 (D2).

생성_파이프라인 5.3절이 지정한 방식입니다. **생성 모델을 지나는 측정(D2 의 on/off 대조)과
검출기 검증을 가르면 표본을 늘리는 비용 없이 증명이 섭니다** - 모델을 부르지 않으므로 이
스크립트는 요금이 0 이고 결정론적입니다.

    python eval/run_guardrail_detector.py
    python eval/run_guardrail_detector.py --json runs/detector.json

⚠️ **이 숫자는 가드레일의 검출력이지 서비스의 위반율이 아닙니다.** 위반율은 생성 경로를
지나야 나오고(`notebooks/hj/verify06_text_cost/run_cost.py`), 그쪽 보고 지표는 델타가 아니라
**절대값과 표본 수**입니다 (2026-08-21 회의). 두 숫자를 한 문장에 섞어 적지 마세요.

⚠️ **파일 이름이 `run_` 으로 시작하는 것은 규약입니다.** `eval/` 은 pytest 수집 대상이라
`test_` 로 지으면 CI 가 이것을 테스트로 집습니다 (eval/README.md). 검출기의 회귀 고정은
`tests/test_guardrail.py` 가 따로 맡고, 이 파일은 **보고용 숫자**를 냅니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from ai_engine.guardrail import check_claims

DATASET = Path(__file__).parent / "golden_dataset" / "guardrail_claims.jsonl"

EXPECTATIONS = ("violation", "clean", "known_gap")
"""예문의 갈래.

- `violation` - 잡아야 합니다. 못 잡으면 검출력 결함입니다
- `clean` - 잡으면 안 됩니다. 잡으면 거짓 양성이고, **전량 거절로 서비스가 아무것도 못
  내보내게 됩니다**
- `known_gap` - **설계된 미검출**입니다 (효능 · 성분 · 제품 식별). 검출률 분모에 넣지
  않습니다 - 사전 없이 판정할 수 없어 대상에서 뺀 것을 실패로 세면 숫자가 거짓말을 합니다
"""


def load(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for row in rows:
        if row["expect"] not in EXPECTATIONS:
            raise ValueError(f"{row['id']}: 모르는 expect 값 {row['expect']!r}")
    return rows


def score(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """예문마다 판정과 기대의 일치 여부. 순수 함수이므로 누구든 같은 결과를 냅니다."""
    scored: list[dict[str, Any]] = []
    for row in rows:
        report = check_claims([row["copy"]], row["evidence"])
        found = sorted({kind for kind, _ in report.violations})

        if row["expect"] == "violation":
            # 갈래까지 맞아야 통과입니다. 잡히기만 하고 갈래가 틀리면 재생성 프롬프트가
            # 엉뚱한 표현을 지목하게 됩니다 (생성_파이프라인 5.1.1절).
            agreed = not report.passed and set(row["kinds"]) <= set(found)
        else:
            agreed = report.passed

        scored.append(
            {
                **row,
                "found": found,
                "matched": [list(violation) for violation in report.violations],
                "agreed": agreed,
            }
        )
    return scored


def summarise(scored: list[dict[str, Any]]) -> dict[str, Any]:
    """갈래별 표본 수와 적중 수. **표본 수를 항상 함께 냅니다** (생성_파이프라인 5.3절)."""
    total = Counter(row["expect"] for row in scored)
    hit = Counter(row["expect"] for row in scored if row["agreed"])
    return {
        expect: {"표본": total[expect], "적중": hit[expect]}
        for expect in EXPECTATIONS
        if total[expect]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--json", type=Path, help="원시 판정을 이 경로에 씁니다")
    args = parser.parse_args()

    scored = score(load(args.dataset))
    summary = summarise(scored)

    for row in scored:
        mark = "  " if row["agreed"] else "!!"
        found = ",".join(row["found"]) or "-"
        print(f"{mark} {row['id']}  {row['expect']:10s} 검출={found:24s} {row['copy']}")

    print()
    labels = {
        "violation": "검출 대상 예문",
        "clean": "정상 카피 (거짓 양성 확인)",
        "known_gap": "설계된 미검출 (분모 밖)",
    }
    for expect, counts in summary.items():
        print(f"{labels[expect]:28s} {counts['표본']}건 중 {counts['적중']}건")

    failed = [row["id"] for row in scored if not row["agreed"]]
    if failed:
        # ⚠️ 패턴을 느슨하게 고쳐 이 줄을 없애지 마세요. 여기서 잡히는 건수가 보고 지표의
        # 분자입니다 - 규칙을 깎으면 검출률이 오르는데, 오른 것은 눈감은 양입니다.
        print(f"\n기대와 어긋난 예문: {', '.join(failed)}", file=sys.stderr)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"summary": summary, "rows": scored}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n원시 판정: {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""지표 채점 하네스 - 수집된 회차 기록을 읽어 개발자_가이드 4절의 지표 표를 채웁니다.

**골격입니다. 수집은 아직 없습니다** (2026-08-22). 채점은 순수 함수라 여기서 끝나지만, 그
함수들이 먹을 기록을 만드는 쪽 - 스택을 띄워 지연을 재고, 채점 모델을 부르고, 브랜드
레퍼런스셋을 임베딩하는 쪽 - 은 08-26 ~ 27 실측의 몫입니다. 무엇이 왜 비어 있는지는
`--describe` 가 함께 출력합니다 (`_pending`).

    python eval/run_metrics.py --describe            # 기록 스키마만 출력. 입력 불필요
    python eval/run_metrics.py --input runs/x.jsonl
    python eval/run_metrics.py --input runs/x.jsonl --json out.json

**수집과 채점을 파일로 가른 것이 이 골격의 요점입니다.** 수집은 비싸고 비결정적이고 외부에
의존하는데, 채점은 순수하고 공짜여야 합니다. 한 스크립트에 두면 지표 정의를 고칠 때마다 회차를
다시 사야 하고, 그러면 아무도 지표를 고치지 않게 됩니다.

⚠️ **데이터가 없는 지표는 0 이 아니라 "측정 안 함" 으로 냅니다.** 0 은 "쟀는데 0 이었다" 로
읽히고, 목표치와 나란히 놓이면 미달로 읽힙니다. 재지 않은 것과 재서 나쁜 것은 다릅니다.

⚠️ 파일 이름이 `run_` 인 것은 규약입니다. `eval/` 은 pytest 수집 대상이라 `test_` 로 지으면
CI 가 이것을 테스트로 집습니다 (eval/README.md).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from metrics import (
    ViolationCount,
    claim_support_rate,
    degraded_rate,
    percentile,
    violation_count,
)

RECORD_SCHEMA = """\
회차 기록 한 줄(JSONL)의 모양입니다. 필드는 전부 선택이고, 없으면 그 지표만 건너뜁니다.

  {
    "runId": "20260826-001",            # 회차 식별자
    "outputType": "single_ad",          # single_ad | comic

    # 생성 지연 (초). 잡 접수부터 결과 이미지 완료까지.
    # ⚠️ backend 를 import 해서 재지 마세요 - 기동된 서비스에 HTTP 로 재야 합니다
    #    (앱 간 import 금지, apps/ai-engine/AGENTS.md).
    "latencySeconds": 52.8,

    # 열화 발생률. 세션당 한 값이고, 한 번 degraded 면 끝까지 degraded 입니다.
    "messageMode": "normal",            # normal | degraded

    # 가드레일 위반 건수. 그 회차가 출력 검증을 통과했는가.
    # ⚠️ 대조군(guardrailApplied=false)의 ClaimReport.passed 를 그대로 넣지 마세요 -
    #    그것은 "통과" 가 아니라 "검사하지 않음" 이라 항상 false 입니다. 하네스가 사후에
    #    check_claims 를 다시 돌린 결과를 넣으세요.
    "guardrailPassed": true,

    # 카피 사실 일치율. 주장 단위 채점 결과이고 채점은 모델이 합니다.
    # ⚠️ 채점 모델 != 생성 모델. 같으면 재는 것이 사실성이 아니라 자기 일치도입니다.
    "claimsSupported": [true, true, false],
    "gradingModel": "<채점에 쓴 모델>",

    # 브랜드 스타일 일치도 - 3절 참고. 지금은 채점하지 않습니다.
    "styleSimilarity": null
  }
"""


def load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} 를 읽지 못했습니다: {exc}") from exc
    return rows


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """기록을 지표로. **가진 데이터가 없는 지표는 결과에서 뺍니다** (0 으로 채우지 않습니다)."""
    scored: dict[str, Any] = {}

    latencies = [float(r["latencySeconds"]) for r in rows if r.get("latencySeconds") is not None]
    if latencies:
        scored["생성 지연"] = {
            "표본": len(latencies),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        }

    modes = [str(r["messageMode"]) for r in rows if r.get("messageMode")]
    if modes:
        scored["열화 발생률"] = {"표본": len(modes), "값": degraded_rate(modes)}

    guardrail = [bool(r["guardrailPassed"]) for r in rows if r.get("guardrailPassed") is not None]
    if guardrail:
        counted: ViolationCount = violation_count(guardrail)
        # 절대값과 표본을 한 몸으로 냅니다. 비율 열을 여기 만들지 마세요 (5.3절).
        scored["가드레일 위반 건수"] = {"표본": counted.sample, "위반": counted.violations}

    graded = [r for r in rows if r.get("claimsSupported")]
    if graded:
        claims = [ok for r in graded for ok in r["claimsSupported"]]
        models = sorted({str(r.get("gradingModel", "미상")) for r in graded})
        scored["카피 사실 일치율"] = {
            "회차": len(graded),
            "주장": len(claims),
            "값": claim_support_rate(claims),
            "채점 모델": models,
            # 주장이 없는 회차는 지표 대상 밖이라 분모에서 빠집니다. 몇 건인지 남겨야
            # "일치율이 높다" 가 "잴 것이 없었다" 를 뜻하는지 읽는 쪽이 압니다.
            "주장 없는 회차": sum(1 for r in rows if not r.get("claimsSupported")),
        }

    return scored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="회차 기록 JSONL")
    parser.add_argument("--json", type=Path, help="채점 결과를 이 경로에 씁니다")
    parser.add_argument("--describe", action="store_true", help="기록 스키마만 출력합니다")
    args = parser.parse_args()

    if args.describe:
        print(RECORD_SCHEMA)
        print(_pending())
        return 0
    if not args.input:
        parser.error("--input 이 필요합니다. 스키마만 보려면 --describe 를 쓰세요")

    rows = load(args.input)
    scored = score(rows)

    print(f"회차 {len(rows)}건 ({args.input})\n")
    for name, value in scored.items():
        print(f"  {name}")
        for key, item in value.items():
            print(f"    {key}: {item}")
    if not scored:
        print("  채점할 수 있는 지표가 없습니다. --describe 로 기록 스키마를 확인하세요.")

    missing = [name for name in _TABLE if name not in scored]
    if missing:
        # ⚠️ 이 줄을 지우지 마세요. 빠진 지표를 조용히 두면 보고서에 네 줄만 적히고,
        #    읽는 사람은 다섯 번째가 나빴는지 안 쟀는지 구별하지 못합니다.
        print(f"\n측정 안 함 (0 이 아닙니다): {', '.join(missing)}")

    print(f"\n{_pending()}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "source": str(args.input),
                    "rows": len(rows),
                    "metrics": scored,
                    "미측정": missing,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"채점 결과: {args.json}")

    return 0


_TABLE = (
    "생성 지연",
    "브랜드 스타일 일치도",
    "카피 사실 일치율",
    "가드레일 위반 건수",
    "열화 발생률",
)
"""개발자_가이드 4절의 지표 표 다섯 행. 목록의 정본은 그 표이고 여기는 사본입니다."""


def _pending() -> str:
    """아직 수집이 없는 자리. **비어 있는 이유가 서로 다르므로 함께 적습니다.**"""
    return (
        "수집이 아직 없는 자리 (08-26 ~ 27 실측의 몫):\n"
        "  - 생성 지연: 스택을 띄워 HTTP 로 재야 합니다. backend 를 import 하면 앱 간 경계\n"
        "    위반이고, 그렇게 잰 값은 배포된 서비스의 지연도 아닙니다\n"
        "  - 카피 사실 일치율: 주장 단위 채점을 붙여야 합니다. 채점 모델 != 생성 모델이고,\n"
        "    어휘 겹침(metrics.source_fidelity)으로 대신하면 안 됩니다 (ADR-0019)\n"
        "  - 브랜드 스타일 일치도: **막혀 있습니다.** 브랜드 레퍼런스셋이 없습니다 - 파인튜닝을\n"
        "    하지 않아 학습 데이터가 없고(ADR-0004), 데이터 출처와 권리 범위는 보류입니다.\n"
        "    임베딩 유사도는 사람 평가와의 상관을 확인한 뒤에만 대리 지표가 됩니다\n"
        "  - 목표치는 다섯 행 모두 TBD 입니다. **실측 전에 적은 숫자는 근거가 아니라 희망입니다**"
    )


if __name__ == "__main__":
    raise SystemExit(main())

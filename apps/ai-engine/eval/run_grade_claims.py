"""채점 하네스 - 수집된 회차의 카피를 주장 단위로 채점해 "카피 사실 일치율" 을 채웁니다.

`run_collect_ad_copy.py` 가 남긴 `texts`(가드레일이 검사한 문구)를 읽어, 각 문구가 담은
주장이 브리프의 근거로 뒷받침되는지를 **채점 모델**에게 묻고 `claimsSupported` 를 붙입니다.
결과 파일을 `run_metrics.py --input` 에 넣으면 그 행이 채워집니다.

⚠️ **채점 모델은 생성 모델과 달라야 합니다.** 같으면 재는 것이 사실성이 아니라 자기 일치도
입니다 (개발자_가이드 4절). 이 스크립트는 `--model` 이 `Settings.text_model` 과 같으면
실행을 거부합니다 - 규약을 주석으로만 두면 언젠가 기본값끼리 만납니다.

⚠️ **생성은 다시 하지 않습니다.** 이미 산 회차를 채점만 하므로 여기서 나가는 비용은 채점
호출뿐입니다. 수집과 채점을 파일로 가른 이유가 이것입니다 (eval/README.md).

⚠️ **어휘 겹침(`metrics.source_fidelity`)으로 대신하지 마세요.** 광고는 근거가 한 문장이고
카피가 짧아 질의응답의 전제가 성립하지 않습니다 - 실측에서 거짓 음성이 났습니다
(ADR-0019). 주장 단위 채점은 모델이 합니다.

    python eval/run_grade_claims.py --input eval/runs/final_on.jsonl --dry-run
    ADGEN_MODEL_API_KEY=sk-... python eval/run_grade_claims.py \\
        --input eval/runs/final_on.jsonl --out eval/runs/graded_on.jsonl --yes

⚠️ 파일 이름이 `run_` 인 것은 규약입니다. `eval/` 은 pytest 수집 대상이라 `test_` 로 지으면
CI 가 이것을 테스트로 집어 외부 API 를 호출합니다 (eval/README.md).
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from ai_engine import draft, usage
from ai_engine.config import Settings
from ai_engine.models import DraftGenerateRequest

logger = logging.getLogger(__name__)

DEFAULT_GOLDEN = Path(__file__).parent / "golden_dataset" / "ad_copy.jsonl"
DEFAULT_MODEL = "gpt-4.1"
"""생성 모델(`gpt-5`)과 다른 것이면 됩니다. 이 값 자체가 실측으로 고른 것은 아니므로
**어느 모델로 채점했는지를 보고서에 함께 적으세요** (`gradingModel` 이 기록에 남습니다)."""

TIMEOUT_S = 60.0

PROMPT = """\
아래는 광고 카피와 그 카피가 근거로 삼아야 할 제품 정보입니다.

카피가 담은 **사실 주장**을 하나씩 골라내고, 각각이 제품 정보로 뒷받침되는지 판정하세요.

판정 규칙:
- 사실 주장만 셉니다. 등장인물의 감정, 바람, 상황 묘사, 권유("지금 담아보세요")는 주장이
  아닙니다.
- 제품 정보에 있는 말을 바꿔 쓴 것은 뒷받침됩니다. 표현이 달라도 뜻이 같으면 참입니다.
- 제품 정보에 없는 수치, 비교, 최상급, 수상 이력, 효능, 성분은 뒷받침되지 않습니다.
- 판단이 서지 않으면 뒷받침되지 않는 것으로 봅니다.

주장이 하나도 없으면 빈 배열을 돌려주세요. 그것은 오류가 아닙니다.

제품 정보:
{evidence}

카피:
{copy}

JSON 으로만 답하세요:
{{"claims": [{{"claim": "<주장>", "supported": true, "why": "<한 문장>"}}]}}
"""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} 를 읽지 못했습니다: {exc}") from exc
    return rows


def evidence_by_case(golden: Path) -> dict[str, str]:
    """케이스별 근거 문자열. **`draft._evidence` 를 그대로 씁니다** - 근거를 이루는 필드
    조합이 2026-08-20 에 한 번 바뀐 적이 있어(생성_파이프라인 5.2절), 여기서 다시 적으면
    그 드리프트가 반복됩니다. `run_collect_ad_copy.py` 의 off 팔이 같은 판단을 합니다."""
    table = {}
    for case in load_jsonl(golden):
        request = DraftGenerateRequest.model_validate({**case["request"], "guardrailApplied": True})
        table[case["id"]] = draft._evidence(request.brief)
    return table


def grade(client: Any, model: str, evidence: str, texts: list[str]) -> list[dict[str, Any]]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": PROMPT.format(evidence=evidence, copy="\n".join(texts))}
        ],
        response_format={"type": "json_object"},
        n=1,
    )
    usage.log_usage(logger, "eval:grade_claims", model, response)
    body = response.choices[0].message.content
    if not body:
        raise RuntimeError("채점 모델이 빈 응답을 돌려줬습니다")
    claims = json.loads(body).get("claims", [])
    if not isinstance(claims, list):
        raise RuntimeError(f"claims 가 리스트가 아닙니다: {type(claims).__name__}")
    return claims


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, required=True, help="수집된 회차 기록 JSONL")
    parser.add_argument("--out", type=Path, default=None, help="채점 결과 (기본: <input>_graded)")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"채점 모델 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="호출 없이 계획만 출력")
    parser.add_argument("--yes", action="store_true", help="실제로 호출합니다 (요금이 나갑니다)")
    args = parser.parse_args()

    settings = Settings()
    if args.model == settings.text_model:
        # 자기채점 편향. 규약이 아니라 실행 조건입니다 (개발자_가이드 4절).
        parser.error(
            f"채점 모델과 생성 모델이 같습니다 ({args.model}). 재는 것이 사실성이 아니라 "
            "자기 일치도가 됩니다. --model 로 다른 모델을 주세요"
        )

    rows = load_jsonl(args.input)
    evidence = evidence_by_case(args.golden)
    # texts 가 없는 회차는 채점 대상이 아닙니다 - 실패/거절/스킵 회차이거나 texts 를 남기기
    # 전에 수집된 것입니다. 여기서 빈 배열을 붙이면 "채점했는데 주장이 0개" 로 읽힙니다.
    targets = [r for r in rows if r.get("texts")]
    if args.limit is not None:
        targets = targets[: args.limit]

    missing = sorted({r["caseId"] for r in targets if r["caseId"] not in evidence})
    if missing:
        parser.error(f"골든셋에 없는 caseId 입니다: {missing}")

    print(f"회차 {len(rows)}건 중 채점 대상 {len(targets)}건 (채점 모델 {args.model})")
    if args.dry_run:
        for row in targets:
            print(f"  {row['caseId']:8} {row['arm']:3} 문구 {len(row['texts'])}줄")
        return 0
    if not args.yes:
        parser.error("--yes 없이는 호출하지 않습니다. 계획만 보려면 --dry-run.")

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - optional extra
        raise SystemExit(
            "openai 패키지가 없습니다. pip install -e './apps/ai-engine[model]'"
        ) from exc
    client = OpenAI(api_key=settings.model_api_key, timeout=TIMEOUT_S, max_retries=0)

    out = args.out or args.input.with_name(f"{args.input.stem}_graded{args.input.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    graded = 0
    failed = 0
    with out.open("w", encoding="utf-8") as handle:
        for i, row in enumerate(rows, 1):
            record = dict(row)
            if row in targets:
                try:
                    claims = grade(client, args.model, evidence[row["caseId"]], row["texts"])
                except Exception as exc:
                    # 채점 실패는 미채점으로 남깁니다. 필드를 비워 두면 run_metrics.py 가
                    # "아직 재지 않음" 으로 세고, 빈 배열로 적으면 "주장이 0개" 가 됩니다.
                    record["gradingError"] = f"{type(exc).__name__}: {exc}"
                    failed += 1
                else:
                    record["claimsSupported"] = [bool(c.get("supported")) for c in claims]
                    record["claimDetail"] = claims  # 사람이 판정을 되짚을 수 있게 남깁니다
                    record["gradingModel"] = args.model
                    graded += 1
                print(f"[{i}/{len(rows)}] {row['caseId']} {row['arm']}")
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()  # 중간에 죽어도 그때까지 산 채점은 남습니다

    print(f"\n{out} 에 기록. 채점 {graded}건, 실패 {failed}건")
    print(f"  python eval/run_metrics.py --input {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""텍스트 세 이음매의 실측 하네스. 단가와 가드레일 위반율을 한 회차에서 얻습니다.

    export ADGEN_MODEL_API_KEY=...              # infra/.env 에 두고 export. 커밋 금지
    export ADGEN_PRICE_INPUT_PER_MTOK=1.25      # 없으면 토큰만 남고 USD 열은 비웁니다
    export ADGEN_PRICE_OUTPUT_PER_MTOK=10.00

    python run_cost.py --dry-run                # 호출 계획과 예상 비용만
    python run_cost.py --rounds 1 --yes         # 스모크
    python run_cost.py --rounds 3 --guardrail both --yes

⚠️ **이음매를 통해서 부릅니다.** 벤더를 직접 부르면 프롬프트가 서비스가 쓰는 문장과 달라지고,
그러면 여기서 잰 단가가 지금 서비스의 단가가 아니게 됩니다 (검증 1순위가 같은 이유로 같은
뼈대를 썼습니다, 03-AI_생성_서빙.md).

⚠️ **`runs/` 는 저장소가 무시합니다.** 회차를 돌린 뒤 요약을 `RESULTS.md` 로 옮기지 않으면
그 결과는 다음 세션에서 사라집니다 - 실제로 2026-08-20 에 그렇게 잃었습니다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import conditions

# 이 레포의 엔진을 씁니다. 설치본이 아니라 체크아웃을 가리켜야 브랜치의 코드를 잽니다.
ENGINE_SRC = Path(__file__).resolve().parents[3] / "apps" / "ai-engine" / "src"
sys.path.insert(0, str(ENGINE_SRC))

from ai_engine import draft, usage  # noqa: E402
from ai_engine.config import Settings  # noqa: E402
from ai_engine.guardrail import check_claims  # noqa: E402
from ai_engine.models import Brief, DraftGenerateRequest, DraftPatch  # noqa: E402
from ai_engine.models import DraftPatchEngineRequest  # noqa: E402
from ai_engine.render_prompt import dialogue_of  # noqa: E402

RUNS_ROOT = Path(__file__).parent / "runs"

# 호출 1회가 요금입니다. 기본을 크게 두면 오타 한 번이 그대로 청구됩니다 (verify01 과 같은 규칙).
DEFAULT_ROUNDS = 1

# 단가는 실측 대상이지 상수가 아닙니다. 벤더 요금표를 확인한 사람이 환경 변수로 넣을 때만 USD
# 열이 채워지고, 없으면 토큰 수만 남습니다 - 추정치를 실측이라고 적지 않기 위함입니다.
PRICE_ENV_INPUT = "ADGEN_PRICE_INPUT_PER_MTOK"
PRICE_ENV_OUTPUT = "ADGEN_PRICE_OUTPUT_PER_MTOK"

USAGE_LINE = re.compile(
    r"seam=(?P<seam>\S+) model=(?P<model>\S+) "
    r"prompt=(?P<prompt>\S+) cached=(?P<cached>\S+) "
    r"completion=(?P<completion>\S+) reasoning=(?P<reasoning>\S+) total=(?P<total>\S+)"
)


class UsageCollector(logging.Handler):
    """엔진이 남기는 `usage` 줄과 가드레일 이벤트를 그대로 주워 담습니다.

    ⚠️ 엔진에서 값을 반환받지 않고 로그를 읽는 이유는, **운영에서 집계할 방법과 같은 경로를
    쓰기 위해서**입니다. 여기만 특별한 통로를 만들면 배포 뒤에 같은 숫자를 못 냅니다.

    ⚠️ **가드레일 이벤트를 함께 담는 것은 on 팔을 읽기 위해서입니다** (2026-08-22 추가).
    재생성은 호출자에게 보이지 않게 설계돼 있어(생성_파이프라인 5.1.1절) 결과만 보면 "통과"와
    "위반했지만 다시 써서 통과"가 같은 값입니다. **그 둘을 못 가르면 on 팔의 관측이
    off 팔과 비교 불가능해집니다** - 위반이 몇 건 일어났는가가 D2 가 세려는 것입니다.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict[str, str]] = []
        self.events: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith("guardrail "):
            self.events.append(message)
            return
        if not message.startswith(f"{usage.PREFIX} "):
            return
        matched = USAGE_LINE.search(message)
        self.records.append(matched.groupdict() if matched else {"raw": message})

    def take(self) -> list[dict[str, str]]:
        taken, self.records = self.records, []
        return taken

    def take_events(self) -> list[str]:
        taken, self.events = self.events, []
        return taken


def usd(records: list[dict[str, str]], price_in: float | None, price_out: float | None) -> Any:
    """토큰을 USD 로. 단가가 없으면 `None` 입니다 - 0 으로 적으면 공짜로 읽힙니다."""
    if price_in is None or price_out is None:
        return None
    total = 0.0
    for record in records:
        prompt, completion = record.get("prompt", "?"), record.get("completion", "?")
        if not prompt.isdigit() or not completion.isdigit():
            return None  # 모르는 값이 하나라도 섞이면 합계도 모릅니다
        total += int(prompt) * price_in / 1e6 + int(completion) * price_out / 1e6
    return round(total, 6)


def run_case(
    case: conditions.Case, guardrail_applied: bool, settings: Settings, collector: UsageCollector
) -> dict[str, Any]:
    """예문 하나를 한 번 돌리고, 카피와 판정과 사용량을 함께 적습니다."""
    brief = Brief.model_validate(conditions.brief_fields(case))
    request = DraftGenerateRequest(
        output_type=case.output_type, brief=brief, guardrailApplied=guardrail_applied
    )

    collector.take()  # 이전 회차의 잔여를 버립니다
    collector.take_events()
    try:
        response = draft.generate_draft(request, settings)
    except Exception as exc:  # 어떤 실패든 회차를 잃지 않는 쪽이 낫습니다
        # ⚠️ **실패도 관측입니다.** 예산 초과(`DraftFailedError`)는 on 팔에서 재생성이
        # 붙을 때 실제로 납니다 - 두 시도가 한 예산을 나눠 쓰기 때문입니다(draft.py
        # `_guarded_draft`). 여기서 예외를 올려 보내면 앞서 돌린 회차의 기록까지 함께
        # 사라지고, **이미 지불한 호출을 다시 사야 합니다** (2026-08-22 실측: 9회분 유실).
        failed = collector.take()
        return {
            "case": case.label,
            "outputType": case.output_type,
            "guardrailApplied": guardrail_applied,
            # 실패해도 이미 끝난 시도의 사용량은 요금입니다. 버리면 합계가 실제보다 작아집니다.
            "usage": failed,
            "calls": len(failed),
            "guardrailEvents": collector.take_events(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    records = collector.take()

    row: dict[str, Any] = {
        "case": case.label,
        "outputType": case.output_type,
        "guardrailApplied": guardrail_applied,
        "usage": records,
        "calls": len(records),
        "guardrailEvents": collector.take_events(),
    }

    if response.draft is None:
        row["refusalReason"] = response.refusal_reason
        return row

    texts = dialogue_of(response.draft)
    # ⚠️ 대조군도 여기서 채점합니다. 엔진은 검사하지 않지만(5.3절) 지표 함수는 순수 함수라
    # 사후에 같은 규칙으로 매길 수 있고, 그 차이가 곧 델타입니다.
    report = check_claims(texts, draft._evidence(brief))
    row["texts"] = list(texts)
    row["passed"] = report.passed
    row["violations"] = [list(violation) for violation in report.violations]
    return row


def run_patch(settings: Settings, collector: UsageCollector) -> list[dict[str, Any]]:
    """부분 교체 1회. 변동 비용이 생기는 유일한 자리라 단가가 따로 필요합니다.

    ⚠️ **기준 시안을 만드는 호출도 요금입니다.** 그 사용량을 버리면 합계가 실제 지출보다
    작아지고, **예산 판단이 그 작은 숫자 위에서 이뤄집니다** (2026-08-20 리뷰 지적, PR #151).
    그래서 두 줄로 나눠 돌려줍니다 - 부분 교체 단가는 뒤의 줄만 봐야 정확하고, 합계는 두 줄을
    다 세야 맞습니다.
    """
    case = conditions.CASES[0]
    brief = Brief.model_validate(conditions.brief_fields(case))

    collector.take()  # 이전 회차의 잔여를 버립니다
    base = draft.generate_draft(
        DraftGenerateRequest(output_type="single_ad", brief=brief), settings
    )
    base_records = collector.take()
    base_row: dict[str, Any] = {
        "case": "draft:patch 기준 시안",
        "usage": base_records,
        "calls": len(base_records),
        "note": "부분 교체를 재려고 만든 시안입니다. 단가 표에는 넣지 말고 합계에는 넣으세요",
    }
    if base.draft is None:
        base_row["error"] = f"기준 시안이 거절됐습니다: {base.refusal_reason}"
        return [base_row]

    patched = draft.patch_draft(
        DraftPatchEngineRequest(
            output_type="single_ad",
            brief=brief,
            draft=base.draft,
            patch=DraftPatch.model_validate({"copy": conditions.PATCH_INSTRUCTION}),
        ),
        settings,
    )
    records = collector.take()
    return [
        base_row,
        {
            "case": "draft:patch",
            "usage": records,
            "calls": len(records),
            "refusalReason": patched.refusal_reason,
        },
    ]


def run_brief_fill(image: Path, settings: Settings, collector: UsageCollector) -> dict[str, Any]:
    """사진 판독 1회. **이 이음매만 입력에 이미지가 실리므로 프롬프트 토큰을 빌더로 셀 수 없습니다.**"""
    from fastapi import UploadFile  # 지연 import - 이 경로에서만 필요합니다

    from ai_engine import brief_fill
    from ai_engine.service_schemas import BriefFillRequest

    case = conditions.CASES[0]
    request = BriefFillRequest(
        product_image=UploadFile(file=BytesIO(image.read_bytes()), filename=image.name),
        product_name=case.product_name,
        selling_point=case.selling_point,
        note=case.note or None,
    )

    collector.take()
    filled = brief_fill.fill_brief(request, settings)
    return {
        "case": "brief:fill",
        "image": str(image),
        "imageBytes": image.stat().st_size,
        "usage": collector.take(),
        "needsInput": filled.needs_input is not None,
    }


def plan(cases: tuple[conditions.Case, ...], rounds: int, arms: list[bool], patch: bool) -> int:
    """최소 호출 수. 가드레일 on 팔은 위반 시 재생성이 붙어 이보다 늘어납니다."""
    return len(cases) * rounds * len(arms) + (2 if patch else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--guardrail", choices=("off", "on", "both"), default="off")
    parser.add_argument("--case", action="append", help="예문 라벨. 반복 지정 가능")
    parser.add_argument("--patch", action="store_true", help="draft:patch 단가도 잽니다 (+2 호출)")
    parser.add_argument("--image", type=Path, help="brief:fill 단가용 제품 사진")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="요금이 나갑니다. 없으면 멈춥니다")
    args = parser.parse_args()

    cases = conditions.CASES
    if args.case:
        wanted = set(args.case)
        cases = tuple(case for case in cases if case.label in wanted)
        if not cases:
            print(f"그런 예문이 없습니다: {sorted(wanted)}", file=sys.stderr)
            return 2

    arms = {"off": [False], "on": [True], "both": [False, True]}[args.guardrail]
    calls = plan(cases, args.rounds, arms, args.patch) + (1 if args.image else 0)

    price_in = _price(PRICE_ENV_INPUT)
    price_out = _price(PRICE_ENV_OUTPUT)

    print(f"예문 {len(cases)}개 x {args.rounds}회차 x {len(arms)}팔 = 최소 {calls}회 호출")
    for case in cases:
        print(f"  - {case.label}: {case.forces}")
    if price_in is None or price_out is None:
        print(f"\n주의: {PRICE_ENV_INPUT} / {PRICE_ENV_OUTPUT} 가 없어 USD 열은 비웁니다.")
    if args.dry_run:
        return 0
    if not args.yes:
        print("\n요금이 나갑니다. 확인했으면 --yes 를 붙이세요.", file=sys.stderr)
        return 1

    key = os.environ.get("ADGEN_MODEL_API_KEY", "")
    if not key:
        print("ADGEN_MODEL_API_KEY 가 비어 있습니다.", file=sys.stderr)
        return 2
    settings = Settings(generation_mode="model", model_api_key=key)

    collector = UsageCollector()
    for name in ("ai_engine.draft", "ai_engine.brief_fill"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.addHandler(collector)

    # ⚠️ **회차마다 파일을 다시 씁니다** (2026-08-22). 예전에는 전부 끝난 뒤 한 번 썼는데,
    # 10번째 호출이 예산 초과로 죽으면서 앞선 9회분 기록이 통째로 사라졌습니다 - 돈은 이미
    # 나갔고 기록만 없는 상태라 같은 호출을 다시 사야 했습니다. 쓰기는 공짜이고 호출은 아닙니다.
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    out = RUNS_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    started_at = datetime.now().isoformat(timespec="seconds")

    rows: list[dict[str, Any]] = []

    def save() -> None:
        out.write_text(
            json.dumps(
                {
                    "startedAt": started_at,
                    "priceInputPerMTok": price_in,
                    "priceOutputPerMTok": price_out,
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    for case in cases:
        for guardrail_applied in arms:
            for index in range(args.rounds):
                row = run_case(case, guardrail_applied, settings, collector)
                row["round"] = index + 1
                row["usd"] = usd(row["usage"], price_in, price_out)
                rows.append(row)
                save()
                print(f"  {row['case']:24s} guard={guardrail_applied!s:5s} -> {_verdict(row)}")

    if args.patch:
        for row in run_patch(settings, collector):
            row["usd"] = usd(row.get("usage", []), price_in, price_out)
            rows.append(row)
        save()
    if args.image:
        row = run_brief_fill(args.image, settings, collector)
        row["usd"] = usd(row.get("usage", []), price_in, price_out)
        rows.append(row)
        save()
    # ⚠️ 기록된 호출 수를 계획과 대조합니다. 사용량을 흘리면 합계가 실제 지출보다 작아지는데,
    # 그 작은 숫자로 예산을 판단하게 됩니다 (2026-08-20 리뷰 지적, PR #151).
    counted = sum(int(row.get("calls", 0)) for row in rows)
    total = sum(row["usd"] for row in rows if row.get("usd") is not None)
    print(f"\n기록된 호출 {counted}회 (계획 최소 {calls}회), 합계 {total:.4f} USD")
    if counted < calls:
        print(f"⚠️ {calls - counted}회의 사용량이 기록되지 않았습니다. 합계가 실제보다 작습니다.")

    print(f"원시 기록: {out}")
    print("⚠️ runs/ 는 커밋되지 않습니다. 요약을 RESULTS.md 로 옮기세요.")
    return 0


def _verdict(row: dict[str, Any]) -> str:
    # ⚠️ 재생성 표시를 빼지 마세요. 엔진은 1회차 위반을 조용히 다시 쓰므로(5.1.1절) 그것
    # 없이는 "통과"와 "위반했다가 다시 써서 통과"가 화면에서 같아 보입니다.
    retried = " +재생성" if row.get("guardrailEvents") else ""
    if row.get("error"):
        return f"실패({row['error']}){retried}"
    if row.get("refusalReason"):
        return f"거절({row['refusalReason']}){retried}"
    if row.get("passed") is True:
        return f"clean{retried}"
    return f"위반 {row.get('violations')}{retried}"


def _price(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())

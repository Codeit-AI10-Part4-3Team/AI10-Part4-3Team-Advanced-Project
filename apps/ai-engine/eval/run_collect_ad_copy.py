"""수집 하네스 - 골든셋(golden_dataset/ad_copy.jsonl)의 각 케이스를 실제로
`draft:generate`에 태워 가드레일 on/off 대조 회차 기록(JSONL)을 만듭니다
(생성_파이프라인 5.1절, D2). `run_metrics.py`가 읽는 "가드레일 위반 건수" 한 줄만
채웁니다 - 그 이상은 이 스크립트의 몫이 아닙니다(아래 "채우지 않는 것" 참고).

⚠️ **on과 off는 서로 다른 파일에 기록됩니다** (`<out>_on.jsonl` / `<out>_off.jsonl`).
같은 파일에 이어 쓰면 `run_metrics.py`가 arm을 모르고 `guardrailPassed`를 전부 합산해,
대조군(off)의 위반이 배포 설정(on)의 위반 건수로 보고됩니다. 두 파일을 각각
`run_metrics.py --input`에 넣으세요.

**요금이 나갈 수 있습니다.** `ADGEN_GENERATION_MODE=model`이고 `ADGEN_MODEL_API_KEY`가
있으면 텍스트 모델(`text_model`, 기본 `gpt-5`)을 케이스당 최대 2회(on/off 팔) x 최대
2회(1차 + 위반 시 재생성)까지 호출합니다. **이미지 생성 API는 부르지 않습니다** -
`draft:generate`는 텍스트(카피/대사)만 만들고, 이미지는 `render`가 별도로 맡습니다.

⚠️ **스텁 모드(기본값)에서도 comic 케이스가 돕니다**(2026-08-27, ADR-0020). 전에는
`_generate_stub`이 만화형을 거절해 comic 16건이 전부 스킵됐습니다. 지금은 여섯 칸이
표시 붙은 고정 문구로 채워져 하네스가 끝까지 지나가지만, **그 회차의 위반 건수는
지표가 아닙니다** - 스텁 문구는 소구점을 그대로 옮긴 것이라 언제나 통과합니다.
가드레일 on/off 대조에 쓸 수 있는 회차는 여전히 실물 모드뿐입니다.

    python eval/run_collect_ad_copy.py --dry-run             # 호출 없이 계획만 출력
    python eval/run_collect_ad_copy.py --yes                 # 실행 (스텁이면 요금 0)
    ADGEN_GENERATION_MODE=model ADGEN_MODEL_API_KEY=sk-... \\
        python eval/run_collect_ad_copy.py --yes --limit 2   # 실물 2건만 먼저 확인

각 회차 기록에는 **가드레일이 검사한 문구 자체가 `texts`로 함께 남습니다.** `trap` 케이스
(효능·성분)는 `check_claims`가 못 잡는 갈래라 사람 판정이 필요한데, 본문이 없으면 그
판정을 하려고 같은 호출을 다시 사야 합니다.

채우지 않는 것:
  - **카피 사실 일치율** - 주장 단위 채점에 별도 채점 모델이 필요합니다(채점 모델 !=
    생성 모델). PR #217이 의도적으로 범위 밖에 둔 것과 같은 이유로 여기서도 안 만듭니다.
  - **생성 지연** - `draft:generate`는 이미지를 안 거치므로 "잡 접수 -> 결과 이미지
    완료"라는 지표 정의와 다른 것을 재게 됩니다. 그 지표는 기동된 서비스에 HTTP로
    재야 합니다(앱 간 import 금지, run_metrics.py의 같은 경고).
  - **열화 발생률(messageMode)** - `brief:fill`/세션 단위 개념이라 `draft:generate`만
    부르는 이 스크립트에서는 관측되지 않습니다.

⚠️ 파일 이름이 `run_`인 것은 규약입니다. `eval/`은 pytest 수집 대상이라 `test_`로
지으면 CI가 이것을 테스트로 집어 외부 API를 호출합니다 (eval/README.md).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from ai_engine import draft, guardrail, render_prompt
from ai_engine.config import Settings
from ai_engine.models import DraftGenerateRequest

DEFAULT_INPUT = Path(__file__).parent / "golden_dataset" / "ad_copy.jsonl"
Arm = Literal["on", "off"]


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} 를 읽지 못했습니다: {exc}") from exc
    return rows


def build_request(case: dict[str, Any], *, guardrail_applied: bool) -> DraftGenerateRequest:
    payload = dict(case["request"])
    payload["guardrailApplied"] = guardrail_applied
    return DraftGenerateRequest.model_validate(payload)


def run_one(case: dict[str, Any], arm: Arm, settings: Settings, run_id: str) -> dict[str, Any]:
    """한 케이스, 한 팔. `guardrailPassed`가 채워지지 않으면 그 회차는 위반 건수
    분모에서 빠집니다(run_metrics.py가 필드 없음과 실측값을 구분하므로 의도된 동작)."""
    request = build_request(case, guardrail_applied=(arm == "on"))
    record: dict[str, Any] = {
        "runId": run_id,
        "mode": settings.generation_mode,  # 스텁 회차를 실측으로 읽지 않기 위해
        "caseId": case["id"],
        "caseType": case["caseType"],
        "guardrailFocus": case["guardrailFocus"],
        "outputType": request.output_type,
        "arm": arm,
    }
    try:
        response = draft.generate_draft(request, settings)
    except NotImplementedError as exc:
        # 미구현 분기. 스텁 + comic 이 여기로 오던 경로는 ADR-0020 으로 사라졌고, 지금 이 갈래를
        # 타는 케이스는 없습니다. 남겨 두는 이유는 다음 미구현 분기가 생겼을 때 이 하네스가
        # 중간에 죽는 대신 그 회차만 건너뛰게 하기 위해서입니다.
        record["skipped"] = str(exc)
        return record
    except draft.DraftFailedError as exc:
        record["error"] = str(exc)
        return record

    record["guardrailApplied"] = response.guardrail_applied
    if response.refusal_reason is not None:
        record["refusalReason"] = response.refusal_reason
        if response.refusal_reason == "guardrail":
            # on 팔에서만 나옵니다 - off 팔은 check_claims를 아예 안 부르므로 이
            # 사유가 나올 수 없습니다(_guarded_attempts).
            record["guardrailPassed"] = False
        # "no_evidence"는 가드레일 위반이 아니라 "쓸 근거가 없어 거절"이라
        # guardrailPassed를 채우지 않고 사유만 남깁니다.
        return record

    assert response.draft is not None
    texts = render_prompt.dialogue_of(response.draft)
    # 생성된 문구 자체를 남깁니다. `trap` 케이스(효능·성분)는 `check_claims`가 구조적으로
    # 못 잡는 갈래라 사람이 회차 출력을 직접 봐야 판정됩니다(eval/README.md의 caseType 표).
    # 판정 결과만 남기고 본문을 버리면 그 판정을 하려고 같은 호출을 다시 사야 합니다 -
    # 2026-08-22 D2 회차가 겪은 유실입니다(가드레일_대조_실측_보고서 D-d절).
    # ⚠️ adPlan과 visualPlan은 넣지 않습니다. 소비자에게 하는 주장이 아니라 제작 지시문이고,
    # 가드레일이 검사하는 것도 여기 담긴 문자열뿐이라 판정 대상이 어긋납니다 (ADR-0019).
    record["texts"] = texts
    if arm == "on":
        if settings.generation_mode == "stub":
            # _generate_stub는 check_claims를 아예 부르지 않습니다(guardrail_applied를
            # 그대로 돌려줄 뿐). "응답이 왔다"를 "통과"로 적으면 검사하지 않은 것을
            # 통과로 기록하게 됩니다 - off 팔에 대한 RECORD_SCHEMA의 경고와 같은
            # 문제가 스텁 on 팔에서 그대로 생깁니다. 필드를 비워 두면 run_metrics.py가
            # 분모에서 뺍니다.
            pass
        else:
            # generate_draft가 이미 검사(+ 위반 시 1회 재생성 후 재검사)까지 끝낸
            # 결과이므로, 시안이 돌아왔다는 것 자체가 최종 통과입니다. 여기서 다시
            # 검사하면 재생성으로 이미 지운 1차 위반까지 통과로 잡혀 on/off 대조가
            # 대칭이 아니게 됩니다.
            record["guardrailPassed"] = True
    else:
        # off 팔은 guardrail_applied=False라 generate_draft가 check_claims를
        # 아예 안 부릅니다. 원본 응답에는 위반 여부가 실려 있지 않으므로 하네스가
        # 사후에 직접 돌려야 합니다 - RECORD_SCHEMA의 경고와 같은 이유입니다.
        # 근거 문자열은 draft._evidence를 그대로 재사용합니다: sellingPoint + note
        # + productName 세 필드를 합치는 규칙이 2026-08-20에 한 번 바뀐 적이 있고
        # (생성_파이프라인 5.2절), 여기서 다시 적으면 그 드리프트가 반복됩니다.
        evidence = draft._evidence(request.brief)
        report = guardrail.check_claims(texts, evidence)
        record["guardrailPassed"] = report.passed
        if report.violations:
            record["violationKinds"] = sorted({kind for kind, _ in report.violations})
    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="회차 기록 출력 경로의 바탕 (기본: runs/ad_copy_<run_id>.jsonl). "
        "on/off 팔을 같은 분모로 합산하면 안 되므로 실제로는 이 경로의 stem에 "
        "_on/_off를 붙인 두 파일에 나눠 씁니다",
    )
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 N건만 (시험 실행용)")
    parser.add_argument("--case", action="append", default=None, help="특정 id만 실행 (반복 가능)")
    parser.add_argument("--dry-run", action="store_true", help="호출 없이 실행 계획만 출력")
    parser.add_argument(
        "--yes", action="store_true", help="실제로 호출합니다 (model 모드면 요금이 나갑니다)"
    )
    args = parser.parse_args()

    settings = Settings()
    cases = load_cases(args.input)
    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            parser.error(f"--case로 지정한 id를 골든셋에서 못 찾았습니다: {sorted(missing)}")
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        parser.error("실행할 케이스가 없습니다 (--input/--case/--limit 확인)")

    comic_n = sum(1 for c in cases if c["request"]["outputType"] == "comic")
    print(
        f"{len(cases)}건 x 2팔(on/off) = {len(cases) * 2}회 호출 예정 (mode={settings.generation_mode})"
    )
    if settings.generation_mode == "stub" and comic_n:
        print(
            f"주의: 스텁 모드라 comic {comic_n}건은 팔마다 스킵됩니다(구현_범위 1절, 만화 미지원)."
        )
    if settings.generation_mode == "model" and not settings.model_api_key:
        print("주의: model 모드인데 ADGEN_MODEL_API_KEY가 비어 있어 모든 호출이 실패로 기록됩니다.")

    if args.dry_run:
        bad = 0
        for c in cases:
            try:
                build_request(c, guardrail_applied=True)
            except ValidationError as exc:
                print(f"  {c['id']:8} 계약 검증 실패: {exc}")
                bad += 1
                continue
            print(
                f"  {c['id']:8} {c['caseType']:11} {c['guardrailFocus']:22} {c['request']['outputType']}"
            )
        if bad:
            print(
                f"\n{bad}건이 DraftGenerateRequest 계약과 어긋납니다. --yes로 돌리기 전에 골든셋을 고치세요."
            )
            return 1
        return 0
    if not args.yes:
        parser.error(
            "--yes 없이는 실행하지 않습니다 (model 모드면 요금이 나갑니다). 계획만 보려면 --dry-run."
        )

    run_id = time.strftime("%Y%m%d-%H%M%S")
    base_out = args.out or Path(__file__).parent / "runs" / f"ad_copy_{run_id}.jsonl"
    base_out.parent.mkdir(parents=True, exist_ok=True)
    # on/off를 같은 파일에 이어 쓰면 run_metrics.py가 arm을 모르고 guardrailPassed를
    # 전부 한 리스트로 합산합니다 - 대조군(off) 위반이 배포 설정(on)의 위반으로 보고되고
    # 표본 수도 두 배로 부풀려집니다. 팔마다 파일을 갈라 이 합산 자체가 나지 않게 합니다
    # (생성_파이프라인 5.3절, "표본 수와 대조군 결과는 따로 적는다").
    out_paths: dict[Arm, Path] = {
        "on": base_out.with_name(f"{base_out.stem}_on{base_out.suffix}"),
        "off": base_out.with_name(f"{base_out.stem}_off{base_out.suffix}"),
    }

    records: list[dict[str, Any]] = []
    handles = {arm: path.open("w", encoding="utf-8") for arm, path in out_paths.items()}
    try:
        for i, case in enumerate(cases, 1):
            for arm in ("on", "off"):
                record = run_one(case, arm, settings, run_id)
                records.append(record)
                handles[arm].write(json.dumps(record, ensure_ascii=False) + "\n")
                handles[arm].flush()  # 회차 중간에 죽어도 그때까지 기록은 남습니다
            print(f"[{i}/{len(cases)}] {case['id']} 완료")
    finally:
        for handle in handles.values():
            handle.close()

    skipped = sum(1 for r in records if "skipped" in r)
    errored = sum(1 for r in records if "error" in r)
    graded = sum(1 for r in records if "guardrailPassed" in r)
    print(
        f"\n{out_paths['on']} (on)와 {out_paths['off']} (off)에 나눠 기록. "
        f"총 {len(records)}줄. 스킵 {skipped}건, 실패 {errored}건, 채점 가능 {graded}건"
    )
    print("다음: 두 팔을 각각 채점하세요 - 합쳐서 채점하면 대조군 위반이 섞입니다.")
    print(f"  python eval/run_metrics.py --input {out_paths['on']}")
    print(f"  python eval/run_metrics.py --input {out_paths['off']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

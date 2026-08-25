"""가드레일 블록의 낱말이 거짓 양성을 유도하는지 가릅니다 (D2 C-b절의 두 갈래).

2026-08-22 D2 회차에서 on 팔이 잡은 award 위반 3건은 전부 **거짓 양성**이었습니다. 근거에
"상을 받았습니다" 가 있는데 모델이 "수상" 으로 줄여 써서 문자열 대조가 걸었습니다. 그 보고서
C-b절이 원인을 두 갈래로 적고 표본이 모자라 가르지 못한 채 남겼습니다.

  1. 표현 유도 - `GUARDRAIL_BLOCK` 의 금지 목록에 "수상 이력" 이라는 낱말이 그대로 있고,
     그 블록은 on 팔에만 붙습니다. 금지어가 오히려 그 낱말을 끌어냈을 수 있습니다
  2. 근거 소진 - "근거에 있는 내용만으로 쓰라" 는 지시가 근거를 남김없이 쓰게 만들었고,
     그 결과 `note` 의 수상 사실이 카피에 들어왔을 수 있습니다

**처방이 다릅니다.** 앞이면 블록의 낱말을 고치는 문제이고, 뒤면 검출기가 의미 대조를 해야
하는 문제입니다 (ADR-0019 재검토).

가르는 방법은 **블록에서 "수상 이력" 만 빼고 나머지를 그대로 두는 것**입니다. 두 갈래의 예측이
갈립니다 - 1번이면 낱말을 뺀 쪽에서 수상 언급이 줄고, 2번이면 두 쪽이 같습니다. "근거만 쓰라"
는 지시는 양쪽에 그대로 있기 때문입니다.

⚠️ **첫 시도만 봅니다.** `draft.generate_draft` 는 1회차 위반을 조용히 재생성하므로
(생성_파이프라인 5.1.1절) 그것을 지나면 "위반했다가 다시 써서 통과" 와 "통과" 가 같은 값으로
보입니다. D2 가 잰 것도 1회차이고, 이 실험이 비교할 대상도 1회차입니다. 그래서 엔진의
재생성 경로를 지나지 않고 프롬프트를 직접 만들어 한 번만 부릅니다.

⚠️ **프롬프트는 `ai_engine.draft_prompt` 에서 가져옵니다.** 판정 대상이 운영 경로의 프롬프트라
여기서 다시 적으면 다른 것을 재게 됩니다 (검증 3순위 도구가 `render_image` 를 그대로 부르는
것과 같은 판단).

    export ADGEN_MODEL_API_KEY=...
    python run_wording.py --rounds 12 --dry-run
    python run_wording.py --rounds 12 --yes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps/ai-engine/src"))

from ai_engine import draft_prompt, guardrail  # noqa: E402
from ai_engine.config import Settings  # noqa: E402
from ai_engine.models import DraftGenerateRequest  # noqa: E402

# 2026-08-22 D2 회차의 `수상_표기_전환` 예문 그대로입니다 (conditions.py). 값을 바꾸면 그
# 회차의 4/5 라는 기준선과 비교할 수 없게 됩니다.
CASE = {
    "outputType": "single_ad",
    "guardrailApplied": True,
    "brief": {
        "productImageUrl": "/eval/golden/d2-award.jpg",
        "productName": "대나무 물티슈",
        "sellingPoint": "무향 무알코올",
        "note": "작년에 지역 박람회에서 상을 받았습니다",
        "category": "생활용품",
        "target": "자녀를 둔 30대",
        "artStyle": "세련된 에디토리얼",
    },
}

WORD = "수상 이력, "
"""블록에서 뺄 낱말. **이것 하나만 뺍니다** - 다른 것을 함께 건드리면 무엇이 차이를 만들었는지
가릴 수 없게 됩니다."""

# 근거의 수상 사실을 카피가 꺼냈는가. 검출기의 award 패턴과는 **다른 것을 셉니다** -
# 저쪽은 금지 표기를 찾고 이쪽은 사실 언급을 찾습니다. 한 자로 재면 두 갈래가 안 갈립니다.
MENTION = re.compile(r"박람회|수상|상을\s*받|받은\s*상|입상|표창")


def build_prompt(strip_word: bool) -> str:
    request = DraftGenerateRequest.model_validate(CASE)
    prompt = draft_prompt.build_generate(request)
    if not strip_word:
        return prompt
    if WORD not in prompt:
        raise SystemExit(
            f"블록에서 {WORD!r} 를 찾지 못했습니다. GUARDRAIL_BLOCK 이 바뀌었다면 이 실험의 "
            "전제가 사라진 것이므로 조건을 다시 세우세요"
        )
    return prompt.replace(WORD, "")


def evidence() -> str:
    brief = CASE["brief"]
    return " ".join(
        part for part in (brief["sellingPoint"], brief["note"], brief["productName"]) if part
    )


def run_round(client: Any, settings: Settings, prompt: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=settings.text_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            n=1,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    body = json.loads(response.choices[0].message.content or "{}")
    # 거절도 정상 응답입니다 (`draft_prompt.REFUSAL_SHAPE`). 카피가 없는 것이지 실패가 아닙니다.
    if "refusal" in body:
        return {"seconds": round(time.monotonic() - started, 1), "refusal": body["refusal"]}

    # ⚠️ 키는 `copy` 입니다. `adCopy` 가 아닙니다 (`draft_prompt.SINGLE_AD_SHAPE`).
    #    2026-08-25 에 이 이름을 틀려 24회차를 빈 문자열로 채점했고, 결과가 오류가 아니라
    #    "언급 0, 검출 0" 이라는 그럴듯한 표로 나왔습니다. 회차를 다시 사야 했습니다.
    #    그래서 아래 검사는 지우지 마세요 - 빈 카피는 관측이 아니라 하네스 고장입니다.
    copy = str(body.get("copy", ""))
    if not copy.strip():
        raise SystemExit(
            f"카피가 비어 있습니다. 모델 응답의 키가 바뀌었는지 확인하세요: {sorted(body)}"
        )
    report = guardrail.check_claims([copy], evidence())
    return {
        "seconds": round(time.monotonic() - started, 1),
        "copy": copy,
        "mentionsAward": bool(MENTION.search(copy)),
        "guardrailPassed": report.passed,
        "violationKinds": sorted({kind for kind, _ in report.violations}),
        "promptTokens": getattr(response.usage, "prompt_tokens", None),
        "completionTokens": getattr(response.usage, "completion_tokens", None),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rounds", type=int, default=12, help="변형당 회차 수")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    variants = {"원본": build_prompt(False), "낱말제거": build_prompt(True)}
    print(f"변형 {len(variants)}종 x {args.rounds}회차 = {len(variants) * args.rounds}회 호출 예정")
    print(f"모델 {settings.text_model} / 프롬프트 {draft_prompt.VERSION}")
    if args.dry_run:
        for name, prompt in variants.items():
            print(f"\n--- {name} ({len(prompt)}자) ---")
            print(prompt[: prompt.find("<근거>")])
        return 0
    if not args.yes:
        parser.error("--yes 없이는 호출하지 않습니다. 계획만 보려면 --dry-run.")
    if settings.generation_mode != "model" or not settings.model_api_key:
        parser.error("ADGEN_GENERATION_MODE=model 과 ADGEN_MODEL_API_KEY 가 필요합니다")

    from openai import OpenAI

    client = OpenAI(
        api_key=settings.model_api_key, timeout=settings.draft_model_timeout_s, max_retries=0
    )

    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = args.out or Path(__file__).parent / "runs" / f"wording_{run_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    # 회차마다 파일을 다시 씁니다. 쓰기는 공짜이고 호출은 아닙니다 (D2 D-d절의 유실).
    with out.open("w", encoding="utf-8") as handle:
        for name, prompt in variants.items():
            for r in range(1, args.rounds + 1):
                row = {
                    "runId": run_id,
                    "variant": name,
                    "round": r,
                    **run_round(client, settings, prompt),
                }
                rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                flag = row.get("error") or (
                    f"언급 {'O' if row['mentionsAward'] else 'X'} / "
                    f"검출 {'통과' if row['guardrailPassed'] else row['violationKinds']}"
                )
                print(f"[{name} {r}/{args.rounds}] {flag}")

    print(f"\n{out}\n")
    for name in variants:
        got = [r for r in rows if r["variant"] == name and "error" not in r]
        mention = sum(1 for r in got if r["mentionsAward"])
        caught = sum(1 for r in got if not r["guardrailPassed"])
        fail = sum(1 for r in rows if r["variant"] == name and "error" in r)
        print(
            f"{name:6} 응답 {len(got):2}/{args.rounds}  수상 언급 {mention:2}  검출 {caught:2}  실패 {fail}"
        )
    print("\n주의: 이 숫자는 1회차 출력입니다. 엔진의 재생성을 지나지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

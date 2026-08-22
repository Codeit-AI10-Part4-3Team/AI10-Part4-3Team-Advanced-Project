"""화풍 8종 예시 이미지 생성 (C4, 미결정_대장 A-3 의 남은 절반).

    python run_styles.py --dry-run          # 프롬프트만 출력. 요금 없음
    python run_styles.py --yes              # 8종 x 1장 (호출 8회)
    python run_styles.py --yes --only 3 7   # 특정 화풍만 다시
    python run_styles.py --yes --with-traits

⚠️ **프롬프트를 여기서 새로 쓰지 않습니다.** `ai_engine.render_prompt.build_panel` 을 그대로
부릅니다. 예시와 실제 결과물의 화풍이 **같은 프롬프트 조각**에서 나와야 한다는 것이 이 작업의
조건이기 때문입니다 (`docs/역할_일정/03-AI_생성_서빙.md`). 문장을 복사해 오면 그 순간부터 두
벌이 되고, 한쪽만 고쳐지는 날 선택 화면이 조용히 거짓말이 됩니다.

⚠️ **결과물은 커밋하지 않습니다.** 저장소가 public 이고 `outputs/` 는 `.gitignore` 142번
줄에 걸립니다 (구현_범위 4.3절). 공유 드라이브로 전달하고, `ADGEN_ART_STYLES` 반영은 05 가
합니다 - 그때 `manifest.csv` 의 `art_style_id` 를 **그대로** 써야 합니다.

티어는 `low` 입니다. 0절 규칙(개발과 검증은 `low`)을 그대로 따릅니다.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import styles
from ai_engine import render_prompt
from ai_engine.models import (
    PANEL_ROLES,
    Brief,
    Character,
    ComicDraft,
    ImageRenderRequest,
    ImageSpec,
    Panel,
)

OUT_ROOT = Path(__file__).resolve().parents[3] / "outputs" / "API_이미지생성_검증" / "화풍_8종_예시"


def _api_key() -> str:
    for name in ("ADGEN_MODEL_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value
    sys.exit("API 키가 없습니다. infra/.env 의 ADGEN_MODEL_API_KEY 를 export 하세요.")


def _request(art_style: str) -> ImageRenderRequest:
    """예시 한 장의 요청. 화풍 말고는 전부 고정입니다.

    ⚠️ 만화형이므로 `character` 가 있고 `aspectRatio` 는 없습니다. 반대로 넣으면
    `check_brief_matches_output_type` 이 거절합니다 - 계약이 유형별로 필드를 가릅니다.
    """
    brief = Brief(
        productImageUrl="",
        productName=styles.PRODUCT_NAME,
        sellingPoint=styles.SELLING_POINT,
        note="",
        category="생활용품",
        target="영유아 자녀를 둔 30대",
        artStyle=art_style,
        character=Character(
            appearance=styles.CHARACTER_APPEARANCE, outfit=styles.CHARACTER_OUTFIT
        ),
    )
    # 6칸을 다 만들지만 **1번 칸만 그립니다.** 계약이 만화형 시안에 6칸을 요구하므로
    # 모양을 맞춰 주는 것이고, 예시로 쓰는 것은 첫 칸 하나입니다. 역할은 `index` 가 정하고
    # 사용자가 고르지 않습니다 (INV-5).
    panels = tuple(
        Panel(index=index, role=role, scene=styles.SCENE, dialogue=styles.DIALOGUE)
        for index, role in enumerate(PANEL_ROLES, start=1)
    )
    return ImageRenderRequest(
        outputType="comic",
        brief=brief,
        draft=ComicDraft(panels=panels, adPlan="화풍 예시용 고정 시안"),
        spec=ImageSpec(width=styles.PANEL_PX * 3, height=styles.PANEL_PX * 2),
        quality="low",
    )


def _prompt_for(style: styles.ArtStyle, *, with_traits: bool) -> tuple[str, str]:
    value = style.prompt_value_with_traits() if with_traits else style.prompt_value
    request = _request(value)
    assert isinstance(request.draft, ComicDraft)
    # 1번 칸은 레퍼런스가 없는 유일한 칸입니다. 예시는 그 칸만 씁니다.
    prompt = render_prompt.build_panel(request, request.draft.panels[0], with_reference=False)
    return value, prompt


def _generate(client: Any, model: str, prompt: str) -> tuple[bytes, float, dict[str, Any]]:
    started = time.time()
    response = client.images.generate(
        model=model,
        prompt=prompt,
        size=f"{styles.PANEL_PX}x{styles.PANEL_PX}",
        quality="low",
        n=1,
    )
    elapsed = time.time() - started
    usage = json.loads(response.usage.model_dump_json()) if response.usage else {}
    return base64.b64decode(response.data[0].b64_json), elapsed, usage


def main() -> int:
    parser = argparse.ArgumentParser(description="화풍 8종 예시 이미지 생성 (C4)")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 출력. 호출하지 않습니다")
    parser.add_argument("--yes", action="store_true", help="요금이 나가는 호출을 승인합니다")
    parser.add_argument("--only", type=int, nargs="*", help="화풍 번호만 골라서 (1 ~ 8)")
    parser.add_argument(
        "--with-traits",
        action="store_true",
        help="artStyle 값에 특징을 함께 실습니다. 이름만으로 구분이 안 될 때만",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="파일 이름 뒤에 붙일 꼬리표. 조건을 바꿔 A/B 로 볼 때 (예: --tag traits)",
    )
    parser.add_argument("--model", default=os.environ.get("ADGEN_IMAGE_MODEL", "gpt-image-2"))
    args = parser.parse_args()

    targets = [s for s in styles.ART_STYLES if not args.only or s.index in args.only]
    if not targets:
        sys.exit("고른 번호에 해당하는 화풍이 없습니다.")

    if args.dry_run:
        for style in targets:
            value, prompt = _prompt_for(style, with_traits=args.with_traits)
            print(f"\n=== {style.index}. {style.name}  (artStyleId={value!r})")
            print(prompt)
        print(f"\n호출하지 않았습니다. 실제 생성은 --yes. 대상 {len(targets)}종.")
        return 0

    if not args.yes:
        sys.exit(f"{len(targets)}회 호출이 나갑니다. 승인하려면 --yes 를 붙이세요.")

    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai 패키지가 없습니다: pip install -r requirements.txt")

    client = OpenAI(api_key=_api_key())
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rows: list[dict[str, Any]] = []

    for style in targets:
        value, prompt = _prompt_for(style, with_traits=args.with_traits)
        try:
            data, elapsed, usage = _generate(client, args.model, prompt)
        except Exception as error:  # noqa: BLE001 - 한 종이 실패해도 나머지는 이어 갑니다
            print(f"  {style.index}. {style.name}: 실패 - {error}")
            rows.append({"index": style.index, "name": style.name, "art_style_id": value,
                         "file": "", "seconds": "", "error": str(error)})
            continue
        suffix = f"-{args.tag}" if args.tag else ""
        path = OUT_ROOT / f"{style.slug}{suffix}.png"
        path.write_bytes(data)
        (OUT_ROOT / f"{style.slug}{suffix}.prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"  {style.index}. {style.name}: {path.name} ({elapsed:.1f}초)")
        rows.append({"index": style.index, "name": style.name, "art_style_id": value,
                     "file": path.name, "seconds": f"{elapsed:.1f}", "error": "",
                     "usage": json.dumps(usage, ensure_ascii=False)})

    manifest = OUT_ROOT / (f"manifest-{args.tag}.csv" if args.tag else "manifest.csv")
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["index", "name", "art_style_id", "file", "seconds", "error", "usage"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})

    ok = sum(1 for row in rows if row["file"])
    print(f"\n{stamp}  성공 {ok}/{len(targets)}  ->  {OUT_ROOT}")
    print(
        "\n다음: 눈으로 8종이 서로 구분되는지 보고, 안 되면 --with-traits 로 다시 돌립니다.\n"
        "전달할 때 manifest.csv 의 art_style_id 를 그대로 넘기세요 - 05 가 "
        "ADGEN_ART_STYLES 에 넣을 값이고, 다르면 예시와 실제 결과가 갈립니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

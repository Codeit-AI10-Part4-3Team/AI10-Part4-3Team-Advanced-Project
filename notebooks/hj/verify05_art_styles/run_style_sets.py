"""화풍별 만화 세트 생성 (검증 5순위, C3).

기획서 15절 5번이 묻는 것은 "화풍 선택이 **결과에** 반영되는지"입니다. C4 의 예시 한 칸과
다릅니다 - 판정 대상이 사용자가 실제로 받는 것, 즉 **6칸 만화 한 세트**여야 합니다.

    python run_style_sets.py --dry-run       # 프롬프트와 비용만. 호출 없음
    python run_style_sets.py --yes           # 8종 x 6칸 = 48회 호출
    python run_style_sets.py --yes --only 2 6

⚠️ **프롬프트도 합성도 여기서 새로 만들지 않습니다. `ai_engine.render.render_image` 를 그대로
부릅니다.** C4 가 `render_prompt.build_panel` 을 부른 것에서 한 걸음 더 간 것이고, 이유는
판정 대상이 달라서입니다 - 5순위가 보는 것은 운영 경로가 내놓은 결과물이므로 컷별 생성,
1번 칸 레퍼런스, 3x2 합성(ADR-0017), 예산과 실패 처리(N20)까지 전부 실물 코드가 해야 합니다.
여기서 호출 모양을 흉내 내면 그 순간부터 두 벌이 되고, 판정 결과를 운영 경로로 옮길 수 없습니다.

⚠️ **결과물은 커밋하지 않습니다.** `outputs/` 는 `.gitignore` 에 걸립니다 (구현_범위 4.3절).
판정 시트와 함께 공유 드라이브로 넘기고, 수치는 회의록과 미결정_대장에 옮깁니다.

판정 시트는 이 폴더가 아니라 `verify01_korean_text_rendering/score_sheet.py` 가 만듭니다:

    python score_sheet.py build --run-dir <아래 OUT_ROOT 의 회차 폴더> \\
        --judges 정승호 임동규 송기하 --task style
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import styles
from ai_engine.config import Settings
from ai_engine.models import (
    PANEL_ROLES,
    Brief,
    Character,
    ComicDraft,
    ImageRenderRequest,
    ImageSpec,
    Panel,
)
from ai_engine.render import RenderFailedError, render_image
from PIL import Image

OUT_ROOT = (
    Path(__file__).resolve().parents[3] / "outputs" / "API_이미지생성_검증" / "검증5순위_화풍반영"
)

SET_COST_USD = {"low": 0.0974, "medium": 0.4041}
"""세트 하나의 실측 단가 (API생성_시험_보고서 E절, 컷별 생성 기준).

`--dry-run` 이 예상 비용을 찍는 데만 씁니다. **작업 상한은 9 USD** 이고(구현_범위 4.2절,
2026-08-22 확정) 8종을 `low` 로 돌리면 약 0.78 USD 입니다.
"""


def _api_key() -> str:
    for name in ("ADGEN_MODEL_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    sys.exit("API 키가 없습니다. infra/.env 의 ADGEN_MODEL_API_KEY 를 export 하세요.")


def _settings(stub: bool) -> Settings:
    """호출 설정.

    ⚠️ **`generation_mode` 를 환경변수에 맡기지 않습니다.** 기본값이 `stub` 이라, 맡기면
    아무 경고 없이 자기 자신과의 일치율을 재게 됩니다 (구현_범위 1.1절). 스텁으로 돌리려면
    `--stub` 을 **명시**해야 하고, 그때는 회차 폴더 이름에 그 사실이 박힙니다.

    ⚠️ **`ADGEN_IMAGE_QUALITY_OVERRIDE` 가 환경에 남아 있으면 그것이 이깁니다**
    (`render._quality`). 끄지 않는 이유는 그 스위치가 존재하는 이유가 바로 이런 실험이기
    때문이고, 발동하면 엔진이 경고 로그를 남깁니다. 다만 `--quality` 로 적은 값과 실제 티어가
    갈리므로 회차 기록에 함께 적습니다 (`conditions.json`).
    """
    if stub:
        return Settings(generation_mode="stub")
    return Settings(generation_mode="model", model_api_key=_api_key())


def _request(art_style: str, quality: str) -> ImageRenderRequest:
    """세트 하나의 요청. **화풍 말고는 전부 고정입니다.**

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
    panels = tuple(
        Panel(index=index, role=role, scene=scene, dialogue=dialogue)
        for index, (role, (scene, dialogue)) in enumerate(
            zip(PANEL_ROLES, styles.PANEL_SCRIPT, strict=True), start=1
        )
    )
    return ImageRenderRequest(
        outputType="comic",
        brief=brief,
        draft=ComicDraft(panels=panels, adPlan="검증 5순위용 고정 시안"),
        spec=ImageSpec(width=styles.PANEL_PX * 3, height=styles.PANEL_PX * 2),
        quality=quality,
    )


def _save_png(payload: bytes, path: Path) -> None:
    """엔진이 돌려준 무손실 WebP 를 PNG 로 옮겨 적습니다.

    ⚠️ **픽셀은 그대로입니다** - 무손실에서 무손실로 옮기므로 판정 대상이 달라지지 않습니다.
    형식을 바꾸는 이유는 하나입니다: 판정자가 열지 못하면 그 회차는 판정에서 빕니다. 시트와
    이미지를 공유 드라이브로 넘기는 경로라 상대가 어떤 뷰어를 쓰는지 우리가 정하지 못합니다.
    """
    with Image.open(io.BytesIO(payload)) as image:
        image.convert("RGB").save(path, format="PNG")


def _dry_run(targets: list[styles.ArtStyle], quality: str) -> int:
    from ai_engine import render_prompt

    # 화풍만 다르고 나머지가 같으므로 프롬프트는 첫 종 하나만 보이면 충분합니다.
    sample = targets[0]
    request = _request(sample.prompt_value, quality)
    assert isinstance(request.draft, ComicDraft)
    print(f"\n=== {sample.index}. {sample.name}  (artStyleId={sample.prompt_value!r})")
    print(render_prompt.build_panel(request, request.draft.panels[0], with_reference=False))

    calls = len(targets) * len(PANEL_ROLES)
    unit = SET_COST_USD.get(quality)
    cost = f"약 ${unit * len(targets):.2f}" if unit else "단가 미실측"
    print(
        f"\n대상 {len(targets)}종 x {len(PANEL_ROLES)}칸 = 호출 {calls}회, 티어 {quality}, {cost}.\n"
        "위 프롬프트는 1번 칸(레퍼런스 없음)입니다. 2번부터는 1번 칸을 레퍼런스로 받습니다.\n"
        "호출하지 않았습니다. 실제 생성은 --yes."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="화풍별 만화 세트 생성 (검증 5순위)")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트와 비용만. 호출 없음")
    parser.add_argument("--yes", action="store_true", help="요금이 나가는 호출을 승인합니다")
    parser.add_argument("--only", type=int, nargs="*", help="화풍 번호만 골라서 (1 ~ 8)")
    parser.add_argument(
        "--with-traits",
        action="store_true",
        help="artStyleId 에 특징을 함께 실습니다. **05 가 ADGEN_ART_STYLES 에 넣을 값과 "
        "같아야 합니다** - 다르면 사용자가 고른 화풍과 판정한 화풍이 갈립니다",
    )
    parser.add_argument(
        "--quality",
        choices=["low", "medium"],
        default="low",
        help="기본 low. 검증 실험은 low 라는 것이 운용 지침입니다 (생성_파이프라인 6.2절) - "
        "판정 축이 화풍이지 티어가 아니기 때문입니다",
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="배관만 확인합니다. 요금이 나가지 않고 **결과는 측정값이 아닙니다** - 스텁이 "
        "그린 판이 나오고 회차 폴더 이름에 STUB 이 박힙니다. 판정에 넘기지 마세요",
    )
    args = parser.parse_args()

    targets = [s for s in styles.ART_STYLES if not args.only or s.index in args.only]
    if not targets:
        sys.exit("고른 번호에 해당하는 화풍이 없습니다.")

    if args.dry_run:
        return _dry_run(targets, args.quality)

    calls = len(targets) * len(PANEL_ROLES)
    if not (args.yes or args.stub):
        sys.exit(f"{len(targets)}종 x {len(PANEL_ROLES)}칸 = {calls}회 호출이 나갑니다. --yes 를 붙이세요.")

    settings = _settings(args.stub)
    # ⚠️ 폴더 이름에 STUB 을 박습니다. 스텁 회차가 실물 회차 옆에 같은 모양으로 놓이면
    #    나중에 어느 쪽이 측정값인지 파일만 보고는 알 수 없습니다 (구현_범위 1.1절).
    marker = "STUB-" if args.stub else ""
    run_dir = OUT_ROOT / f"{marker}{datetime.now().astimezone():%Y%m%d-%H%M%S}-style_{args.quality}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for style in targets:
        value = style.prompt_value_with_traits() if args.with_traits else style.prompt_value
        started = time.monotonic()
        try:
            payload = render_image(_request(value, args.quality), settings)
        except Exception as error:  # noqa: BLE001 - RenderFailedError 와 벤더 예외를 함께
            # ⚠️ 한 종이 실패해도 나머지를 이어 갑니다. 세트 **안**에서 칸 하나가 실패하면
            # 세트 전체가 버려지는 것은 엔진이 이미 하고(N20-a), 여기서 잇는 것은 **종끼리**
            # 입니다 - 8종 중 하나 때문에 나머지 7종의 요금을 다시 쓸 이유가 없습니다.
            print(f"  {style.index}. {style.name}: 실패 - {error}")
            rows.append({"run_id": style.index, "art_style_id": value, "error": str(error)})
            continue
        elapsed = time.monotonic() - started

        path = run_dir / f"{style.slug}.png"
        _save_png(payload, path)
        print(f"  {style.index}. {style.name}: {path.name} ({elapsed:.1f}초)")
        rows.append(
            {
                "run_id": style.index,
                "variant": "style",
                "image_file": path.name,
                "art_style_id": value,
                "seconds": f"{elapsed:.1f}",
                "error": "",
            }
        )

    # ⚠️ 파일 이름이 `sets.csv` 인 것은 score_sheet 가 그 이름을 **먼저** 보기 때문입니다.
    #    판정 단위가 호출(칸)이 아니라 합성된 세트라, 이 목록이 곧 판정 시트의 행입니다.
    #    `art_style_id` 열이 없으면 `--task style` 이 그 자리에서 멈춥니다.
    with (run_dir / "sets.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["run_id", "variant", "image_file", "art_style_id", "seconds", "error"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})

    (run_dir / "conditions.json").write_text(
        json.dumps(
            {
                "generation_mode": settings.generation_mode,
                "quality_requested": args.quality,
                "quality_override": settings.image_quality_override or None,
                "with_traits": args.with_traits,
                "image_model": settings.image_model,
                "panel_script": list(styles.PANEL_SCRIPT),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    ok = sum(1 for row in rows if row.get("image_file"))
    print(f"\n성공 {ok}/{len(targets)}종  ->  {run_dir}")
    if settings.image_quality_override:
        print(
            f"주의: ADGEN_IMAGE_QUALITY_OVERRIDE={settings.image_quality_override} 가 "
            f"요청 티어 {args.quality} 를 덮었습니다. 회차 기록에 함께 적으세요."
        )
    print(
        "\n다음: 판정 시트를 만들어 판정자 세 분께 이미지와 함께 넘기세요.\n"
        f"  cd ../verify01_korean_text_rendering && python score_sheet.py build \\\n"
        f"      --run-dir {run_dir} --judges 정승호 임동규 송기하 --task style"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

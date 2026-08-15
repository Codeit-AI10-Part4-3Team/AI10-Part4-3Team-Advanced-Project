"""컷별 생성 + 후처리 합성 - A-2가 조건부 경로로 남겨 둔 방식의 실측.

한 장에 6칸을 그리게 하는 대신 **칸을 하나씩 만들어 우리가 붙입니다.** 미결정_대장 A-2는 이
방식을 "호출 수가 컷 수만큼 늘어나 비용 부담이 크다"는 이유로 조건부 경로로 남겼습니다. 그
비용이 실제로 얼마인지, 그리고 인물과 제품이 칸 사이에서 유지되는지가 여기서 나옵니다.

한 장 생성 방식과 견줄 때 바뀌는 것:

| | 한 장에 6칸 | 컷별 생성 + 합성 |
|---|---|---|
| 호출 수 | 1 | 6 |
| 칸 크기 | 1101 ~ 1142px 로 흔들림 (실측) | **정확히 1152px** - 우리가 붙이므로 |
| 바깥 여백 | 14 ~ 36px 로 흔들림 (실측) | **0px** |
| 인물 일관성 | 모델이 한 번에 처리 | **칸마다 새로 그리므로 이 실험의 핵심 물음** |

인물과 제품을 유지하는 수단은 첫 칸을 레퍼런스로 넘기는 것입니다. 제품컷 입력 실험에서
`images.edit` 가 입력 제품을 5/5 로 보존했으므로, 같은 성질을 인물에 쓰는 셈입니다.

    python run_panels.py --sets 1                 # 스모크 1세트 (6회 호출)
    python run_panels.py --sets 3 --yes

⚠️ **1세트가 6회 호출입니다.** `--sets` 를 회차 수로 착각하면 비용이 6배가 됩니다.
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

import conditions
from PIL import Image

RUNS_ROOT = Path(__file__).parent / "runs"

PANEL_PROMPT_HEAD = (
    "정사각형 만화 한 칸. 격자나 여러 칸으로 나누지 않는다. 한 장면만 그린다.\n"
    f"{conditions.PRODUCT_NAME} 광고의 한 컷이다.\n"
)

REFERENCE_INSTRUCTION = (
    "입력으로 준 이미지에 나온 **인물과 제품을 그대로 유지한다.** 얼굴, 머리 모양, 복장, "
    "제품 패키지의 색과 문구가 같아야 한다. 장면과 동작만 아래 지시대로 바꾼다.\n"
)


def panel_prompt(panel: conditions.Panel, with_reference: bool) -> str:
    """칸 하나의 프롬프트. 대사는 1순위와 같은 문장을 씁니다 - 바꾸면 비교가 깨집니다."""
    head = PANEL_PROMPT_HEAD
    if with_reference:
        head += REFERENCE_INSTRUCTION
    return (
        f"{head}{conditions._STYLE_BASE}\n{conditions._GROUNDING_INSTRUCTION}\n\n"
        f"장면: {panel.scene}.\n"
        f'말풍선을 하나 그리고 그 안에 "{panel.line}" 를 오탈자 없이 정확히 그대로 표기한다. '
        "그 밖의 문구는 이미지에 넣지 않는다."
    )


def _api_key() -> str:
    for name in ("ADGEN_MODEL_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    sys.exit("API 키가 없습니다. infra/.env의 ADGEN_MODEL_API_KEY를 export 하세요.")


def _prices() -> dict[str, float | None]:
    def read(name: str) -> float | None:
        raw = os.environ.get(name, "").strip()
        return float(raw) if raw else None

    return {
        "text_in": read("ADGEN_PRICE_INPUT_PER_MTOK"),
        "image_in": read("ADGEN_PRICE_IMAGE_INPUT_PER_MTOK"),
        "out": read("ADGEN_PRICE_OUTPUT_PER_MTOK"),
    }


def _cost(usage: dict[str, Any], prices: dict[str, float | None]) -> float | None:
    if prices["text_in"] is None or prices["out"] is None:
        return None
    details = usage.get("input_tokens_details") or {}
    image_in = details.get("image_tokens") or 0
    text_in = details.get("text_tokens") or 0
    price_image = prices["image_in"] if prices["image_in"] is not None else prices["text_in"]
    return (
        text_in / 1_000_000 * prices["text_in"]
        + image_in / 1_000_000 * price_image
        + (usage.get("output_tokens") or 0) / 1_000_000 * prices["out"]
    )


def _generate(
    client: Any, model: str, prompt: str, size: str, ref: Path | None, quality: str | None
) -> tuple:
    started = time.monotonic()
    kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "n": 1}
    if quality:
        kwargs["quality"] = quality
    if ref is None:
        response = client.images.generate(**kwargs)
    else:
        with ref.open("rb") as fp:
            response = client.images.edit(image=[fp], **kwargs)
    elapsed = time.monotonic() - started

    payload = response.data[0]
    if not getattr(payload, "b64_json", None):
        sys.exit("응답에 b64_json이 없습니다.")
    usage = getattr(response, "usage", None)
    usage_dict = dict(usage.model_dump()) if hasattr(usage, "model_dump") else {}
    return base64.b64decode(payload.b64_json), round(elapsed, 2), usage_dict


def compose(panel_paths: list[Path], out_path: Path) -> tuple[int, int]:
    """6칸을 3 x 2 격자로 붙입니다.

    규격(기획서 10.2)은 칸 1152 x 1152, 캔버스 3456 x 2304 입니다. 3 x 1152 = 3456 이므로
    **경계선과 바깥 여백이 들어갈 자리가 없습니다.** 한 장 생성에서 칸이 1101 ~ 1142px 로
    나온 이유가 이것입니다 - 모델은 경계선을 그리라는 지시를 지키려고 칸을 줄였습니다.
    여기서는 칸을 맞대어 붙이고 경계선은 칸 위에 덧그립니다.
    """
    canvas = Image.new("RGB", (conditions.CANVAS_WIDTH, conditions.CANVAS_HEIGHT), (255, 255, 255))
    for index, path in enumerate(panel_paths):
        with Image.open(path) as panel:
            resized = panel.resize(
                (conditions.PANEL_WIDTH, conditions.PANEL_HEIGHT), Image.LANCZOS
            )
            x = (index % conditions.PANEL_COLS) * conditions.PANEL_WIDTH
            y = (index // conditions.PANEL_COLS) * conditions.PANEL_HEIGHT
            canvas.paste(resized, (x, y))
    canvas.save(out_path)
    return canvas.size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sets", type=int, default=1, help="세트 수. 1세트 = 6회 호출")
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--model", default=os.environ.get("ADGEN_IMAGE_MODEL", "gpt-image-2"))
    parser.add_argument(
        "--reference",
        choices=["first", "chain", "none"],
        default="first",
        help="first=1번 칸을 모든 칸의 레퍼런스로, chain=직전 칸을 레퍼런스로, none=레퍼런스 없음",
    )
    parser.add_argument(
        "--quality",
        choices=["low", "medium", "high"],
        default=None,
        help="주지 않으면 모델이 칸마다 티어를 골라 세트 비용이 흔들립니다 "
        "(실측: 같은 세트 안에서 출력 토큰 213 ~ 1917, 9배)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    size = f"{conditions.PANEL_WIDTH}x{conditions.PANEL_HEIGHT}"

    if args.dry_run:
        print(f"[dry-run] size={size} reference={args.reference} 호출 {args.sets * 6}회")
        print("-" * 72)
        print(panel_prompt(conditions.PANELS[0], with_reference=False))
        print("-" * 72)
        print(panel_prompt(conditions.PANELS[1], with_reference=args.reference != "none"))
        return 0

    calls = args.sets * conditions.PANEL_COUNT
    if not args.yes:
        answer = input(f"{args.sets}세트 = {calls}회 호출합니다. 진행합니까? [y/N] ")
        if answer.strip().lower() != "y":
            return 1

    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai 패키지가 없습니다: pip install -r requirements.txt")

    client = OpenAI(api_key=_api_key())
    prices = _prices()
    suffix = f"-panels-{args.quality}" if args.quality else "-panels"
    run_dir = RUNS_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)

    fields = [
        "set_id",
        "panel",
        "reference",
        "elapsed_sec",
        "text_in",
        "image_in",
        "output_tokens",
        "cost_usd",
        "file",
    ]
    grand_total = 0.0

    with (run_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()

        for set_id in range(args.start_id, args.start_id + args.sets):
            panel_paths: list[Path] = []
            set_cost = 0.0
            set_time = 0.0

            for panel in conditions.PANELS:
                ref: Path | None = None
                if args.reference == "first" and panel_paths:
                    ref = panel_paths[0]
                elif args.reference == "chain" and panel_paths:
                    ref = panel_paths[-1]

                prompt = panel_prompt(panel, with_reference=ref is not None)
                data, elapsed, usage = _generate(
                    client, args.model, prompt, size, ref, args.quality
                )

                path = run_dir / f"set{set_id:02d}-panel{panel.index}.png"
                path.write_bytes(data)
                panel_paths.append(path)

                details = usage.get("input_tokens_details") or {}
                cost = _cost(usage, prices)
                set_cost += cost or 0.0
                set_time += elapsed
                writer.writerow(
                    {
                        "set_id": set_id,
                        "panel": panel.index,
                        "reference": ref.name if ref else "",
                        "elapsed_sec": elapsed,
                        "text_in": details.get("text_tokens"),
                        "image_in": details.get("image_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                        "cost_usd": f"{cost:.4f}" if cost is not None else "",
                        "file": path.name,
                    }
                )
                fp.flush()
                with (run_dir / "calls.jsonl").open("a", encoding="utf-8") as raw:
                    raw.write(
                        json.dumps(
                            {"set_id": set_id, "panel": panel.index, "usage": usage},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                print(f"  set{set_id:02d} panel{panel.index} {elapsed}s tok={usage.get('output_tokens')}")

            composed = run_dir / f"panels-{set_id:02d}.png"
            width, height = compose(panel_paths, composed)
            grand_total += set_cost
            print(
                f"set{set_id:02d} 합성 -> {composed.name} {width}x{height} "
                f"/ {set_time:.1f}s / ${set_cost:.4f}\n"
            )

    (run_dir / "prompt.txt").write_text(
        panel_prompt(conditions.PANELS[0], with_reference=False)
        + "\n\n=== 2번 칸부터 (레퍼런스 동반) ===\n\n"
        + panel_prompt(conditions.PANELS[1], with_reference=args.reference != "none"),
        encoding="utf-8",
    )
    print(f"결과: {run_dir}")
    if grand_total:
        print(f"실측 비용: {args.sets}세트 합계 ${grand_total:.4f} / 1세트당 ${grand_total / args.sets:.4f}")
        print(f"참고: 한 장 생성 방식은 1회 $0.1171 이었습니다 (2026-08-13 ~ 14 실측)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

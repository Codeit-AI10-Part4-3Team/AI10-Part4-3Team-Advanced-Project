"""검증 1순위(6칸 한국어 렌더링)와 6순위(비용 실측)를 한 번의 실행으로 얻는 하네스.

두 검증을 합친 이유: 호출 1회가 곧 비용이라 따로 돌리면 같은 돈을 두 번 씁니다. 1순위를 돌리는
동안 usage와 소요 시간을 그대로 적어 두면 6순위의 단가는 추가 호출 없이 나옵니다.

사용법:

    export ADGEN_MODEL_API_KEY=...
    python run_experiment.py --runs 1              # 스모크 1회 (단가와 규격 확인)
    python run_experiment.py --runs 20             # 본 회차
    python run_experiment.py --runs 20 --variant fallback

산출물은 `runs/<타임스탬프>/`에 남고 커밋되지 않습니다 (이미지가 크고 저장소가 public).
판정에 쓸 이미지는 팀 공유 드라이브로 올리세요 (구현_범위 4.3절).
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

RUNS_ROOT = Path(__file__).parent / "runs"

# 호출 1회가 요금입니다. 기본값을 20으로 두면 오타 한 번이 20회 호출이 되므로 기본은 1입니다.
DEFAULT_RUNS = 1

# 단가는 실측 대상이지 상수가 아닙니다. 벤더 요금표를 확인한 사람이 환경 변수로 넣으면 그때만
# 비용 열이 채워지고, 없으면 토큰 수만 남습니다 - 추정치를 실측이라고 적지 않기 위함입니다
# (구현_범위 4.2절: 예산 상한은 실측 뒤에 정합니다).
PRICE_ENV_INPUT = "ADGEN_PRICE_INPUT_PER_MTOK"
PRICE_ENV_OUTPUT = "ADGEN_PRICE_OUTPUT_PER_MTOK"


def _api_key() -> str:
    """저장소 규약 이름을 먼저 봅니다. 흔한 이름도 받되 어느 쪽을 썼는지 알립니다."""
    for name in ("ADGEN_MODEL_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            if name != "ADGEN_MODEL_API_KEY":
                print(f"주의: {name}를 사용합니다. 저장소 규약 이름은 ADGEN_MODEL_API_KEY입니다.")
            return value
    sys.exit(
        "API 키가 없습니다. infra/.env에 ADGEN_MODEL_API_KEY를 넣고 export 하세요.\n"
        "키를 커밋하지 마세요 - 이 저장소는 public이고 복구는 revert가 아니라 폐기와 재발급입니다."
    )


def _prices() -> tuple[float | None, float | None]:
    def read(name: str) -> float | None:
        raw = os.environ.get(name, "").strip()
        return float(raw) if raw else None

    return read(PRICE_ENV_INPUT), read(PRICE_ENV_OUTPUT)


def _usage_dict(usage: Any) -> dict[str, Any]:
    """SDK 버전마다 usage 타입이 달라 그대로 직렬화합니다. 없으면 빈 dict."""
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return dict(usage.model_dump())
    if isinstance(usage, dict):
        return dict(usage)
    return {"raw": repr(usage)}


def _cost(usage: dict[str, Any], price_in: float | None, price_out: float | None) -> float | None:
    if price_in is None or price_out is None:
        return None
    tok_in = usage.get("input_tokens")
    tok_out = usage.get("output_tokens")
    if tok_in is None or tok_out is None:
        return None
    return (tok_in / 1_000_000) * price_in + (tok_out / 1_000_000) * price_out


def _call_once(
    client: Any, model: str, prompt: str, size: str, quality: str | None
) -> tuple[bytes, dict[str, Any]]:
    """이미지 1장. 실패는 삼키지 않고 올립니다 - 규격 거절 자체가 이 실험의 발견입니다.

    ⚠️ `quality`를 주지 않으면 모델이 회차마다 티어를 고릅니다 (2026-08-13 실측: 같은 조건
    10회에서 출력 토큰이 1674와 3826으로 갈렸고 비용이 2.3배 차이났습니다). 조건을 고정해야
    하는 실험에서는 명시하세요. 받는 값은 확인되지 않아 기본은 미지정으로 둡니다 - 잘못된
    값을 기본값으로 박으면 전 회차가 400으로 죽습니다.
    """
    kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "n": 1}
    if quality:
        kwargs["quality"] = quality

    started = time.monotonic()
    response = client.images.generate(**kwargs)
    elapsed = time.monotonic() - started

    payload = response.data[0]
    if getattr(payload, "b64_json", None):
        image_bytes = base64.b64decode(payload.b64_json)
    else:
        sys.exit(
            "응답에 b64_json이 없습니다. URL 응답이면 다운로드 경로를 추가해야 합니다 - "
            "이 하네스는 인라인 바이트만 다룹니다."
        )

    meta = {
        "elapsed_sec": round(elapsed, 2),
        "usage": _usage_dict(getattr(response, "usage", None)),
        "model": model,
        "size": size,
    }
    return image_bytes, meta


def _write_image(path: Path, data: bytes) -> tuple[int, int]:
    """원본 바이트를 그대로 저장하고 실제 해상도를 돌려줍니다.

    ⚠️ 재인코딩하지 않습니다. 손실 압축을 한 번 거치면 판정자가 모델의 렌더링이 아니라 압축
    아티팩트를 보게 됩니다 (render.py의 lossless WebP 주석과 같은 이유).
    """
    path.write_bytes(data)
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 - 크기 확인 실패가 회차를 중단시킬 이유는 없습니다
        return (0, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="생성 횟수 (기본 1)")
    parser.add_argument(
        "--variant",
        choices=sorted(conditions.VARIANTS),
        default="main",
        help="main=대사까지 그림(본안), fallback=말풍선만(예비안)",
    )
    parser.add_argument(
        "--size",
        default=None,
        help="요청 해상도. 주지 않으면 variant 의 기본 규격을 씁니다 "
        "(만화형 3456x2304, 단일 광고형 1088x1088)",
    )
    parser.add_argument("--model", default=os.environ.get("ADGEN_IMAGE_MODEL", "gpt-image-2"))
    parser.add_argument(
        "--quality",
        default=None,
        help="지정하면 그대로 전달합니다. 주지 않으면 모델이 회차마다 티어를 골라 조건이 흔들립니다",
    )
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 출력하고 호출하지 않음")
    parser.add_argument("--yes", action="store_true", help="비용 확인 프롬프트를 건너뜀")
    parser.add_argument(
        "--start-id",
        type=int,
        default=1,
        help="회차 번호의 시작값. 같은 조건으로 회차를 이어 붙일 때 씁니다 - 판정 시트에서 "
        "앞선 회차와 번호가 겹치면 판정자가 같은 그림을 두 번 보게 됩니다",
    )
    args = parser.parse_args()

    prompt = conditions.VARIANTS[args.variant]()
    if args.size is None:
        width, height = conditions.DEFAULT_SIZE[args.variant]
        args.size = f"{width}x{height}"

    if args.dry_run:
        print(f"[dry-run] model={args.model} size={args.size} variant={args.variant}")
        print("-" * 72)
        print(prompt)
        return 0

    if args.runs > 1 and not args.yes:
        answer = input(f"{args.runs}회 호출합니다. 스모크 1회를 먼저 돌렸습니까? [y/N] ")
        if answer.strip().lower() != "y":
            print("중단했습니다. --runs 1로 단가를 먼저 재세요.")
            return 1

    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai 패키지가 없습니다: pip install -r requirements.txt")

    client = OpenAI(api_key=_api_key())
    price_in, price_out = _prices()
    if price_in is None or price_out is None:
        print(
            f"주의: {PRICE_ENV_INPUT} / {PRICE_ENV_OUTPUT}가 없어 비용 열이 비어 있습니다. "
            "토큰 수는 그대로 남으므로 요금표 확인 후 곱하면 됩니다."
        )

    run_dir = RUNS_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}-{args.variant}"
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.csv"
    raw_path = run_dir / "calls.jsonl"

    fields = [
        "run_id",
        "variant",
        "model",
        "requested_size",
        "actual_width",
        "actual_height",
        "elapsed_sec",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "image_file",
        "error",
    ]
    total_cost = 0.0
    priced_calls = 0

    with manifest_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()

        for run_id in range(args.start_id, args.start_id + args.runs):
            row: dict[str, Any] = {"run_id": run_id, "variant": args.variant, "model": args.model}
            row["requested_size"] = args.size
            try:
                image_bytes, meta = _call_once(
                    client, args.model, prompt, args.size, args.quality
                )
            except Exception as exc:  # noqa: BLE001 - 벤더 예외 계층에 의존하지 않습니다
                row["error"] = f"{type(exc).__name__}: {exc}"
                writer.writerow(row)
                fp.flush()
                print(f"[{run_id}] 실패: {row['error']}")
                # 첫 회차 실패는 규격이나 키 문제일 가능성이 높아 반복하면 돈만 씁니다.
                if run_id == args.start_id:
                    print("첫 회차에서 실패해 중단합니다. 원인을 확인하고 다시 시작하세요.")
                    return 1
                continue

            image_file = f"{args.variant}-{run_id:02d}.png"
            width, height = _write_image(run_dir / image_file, image_bytes)
            usage = meta["usage"]
            cost = _cost(usage, price_in, price_out)
            if cost is not None:
                total_cost += cost
                priced_calls += 1

            row.update(
                actual_width=width,
                actual_height=height,
                elapsed_sec=meta["elapsed_sec"],
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cost_usd=f"{cost:.4f}" if cost is not None else "",
                image_file=image_file,
                error="",
            )
            writer.writerow(row)
            fp.flush()
            with raw_path.open("a", encoding="utf-8") as raw_fp:
                raw_fp.write(json.dumps({"run_id": run_id, **meta}, ensure_ascii=False) + "\n")

            note = ""
            if (width, height) != (0, 0) and args.size != f"{width}x{height}":
                note = f"  ⚠️ 요청 {args.size} != 실제 {width}x{height}"
            print(
                f"[{run_id}] {image_file} {width}x{height} "
                f"{meta['elapsed_sec']}s tokens={usage.get('output_tokens')}{note}"
            )

    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"\n결과: {run_dir}")
    if priced_calls:
        print(f"실측 비용: {priced_calls}회 합계 ${total_cost:.4f} / 1회당 ${total_cost / priced_calls:.4f}")
    print("다음: python score_sheet.py build --run-dir " + str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

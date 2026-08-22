"""판정이 고른 예시 8장을 05 에게 넘길 형태로 만듭니다 (C4).

    python prepare_handoff.py                 # 제안대로 (1 만 특징 포함)
    python prepare_handoff.py --traits 1 6    # 1 과 6 을 특징 포함으로
    python prepare_handoff.py --traits        # 전부 이름만

⚠️ **어느 조건을 넘길지는 아직 확정이 아닙니다.** 기본값은 판정 다수결에서 나온 **제안**
이고(1 만 만장일치로 특징 포함, 나머지는 이름만 또는 `둘 다`), 확정은 A-3 소관자와 05 의
몫입니다. `--traits` 로 언제든 바꿔 다시 만들 수 있게 해 둔 이유가 그것입니다 - 값이
정해지고 나서 한 번 더 돌리면 됩니다.

**`art_style_id` 는 손으로 적지 않습니다.** 이미지를 실제로 만든 문자열을 `manifest.csv` /
`manifest-traits.csv` 에서 그대로 읽어 옵니다. 옮겨 적다 한 글자가 틀리면 사용자가 본 예시와
실제 결과가 다른 프롬프트에서 나옵니다(`render_prompt._common_head` 의 `화풍은 {...}.`).

**PNG 를 그대로 넘기지 않습니다.** 원본은 장당 약 2MB 라 8장이면 15MB 가 넘고, 그것이 화풍
선택 화면 한 번에 전부 내려갑니다. 크기는 1152 px 그대로 두고 WebP 로만 다시 인코딩하면
합계가 약 1MB 로 줄어듭니다. 해상도를 깎지 않는 이유는 확대 보기(`.art-zoom`, 최대 560 CSS px)
가 고밀도 화면에서 두 배를 쓰기 때문이고, 파일이 하나인 이유는 계약의 `ArtStyle` 에
`exampleImageUrl` 이 하나뿐이기 때문입니다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import styles
from PIL import Image

SOURCE = Path(__file__).resolve().parents[3] / "outputs" / "API_이미지생성_검증" / "화풍_8종_예시"
HANDOFF = SOURCE / "전달"

TRAITS_BY_DEFAULT = (1,)
"""특징 포함으로 넘길 화풍 번호의 **제안**. 확정이 아닙니다.

1번(심플 플랫 웹툰)만 판정자 3명 만장일치였고, 자유 응답에서 2명이 독립으로 지적한
"1 과 2 가 비슷하다" 도 1 에 특징을 붙이면 평면 채색으로 갈리며 풀립니다. 나머지 7종은
다수결이 이름만이거나 `둘 다`(차이 없음) 라 더 짧은 쪽을 둡니다.
"""

WEBP_QUALITY = 82
"""화풍을 보여 주는 그림이라 질감이 뭉개지면 판정 자체가 무의미해집니다. 82 는 원본과
눈으로 구분되지 않으면서 PNG 대비 15배가 줄어드는 지점입니다 (실측, 8장 15.6MB -> 1.0MB).
"""


def _art_style_ids(with_traits: bool) -> dict[int, str]:
    """이미지를 만든 `art_style_id` 를 manifest 에서 읽습니다. 손으로 옮기지 않습니다."""
    manifest = SOURCE / ("manifest-traits.csv" if with_traits else "manifest.csv")
    if not manifest.exists():
        raise SystemExit(f"manifest 가 없습니다: {manifest}")
    with manifest.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    ids = {}
    for row in rows:
        if row["error"]:
            raise SystemExit(f"{manifest.name} 의 {row['index']}번 행이 실패로 남아 있습니다")
        ids[int(row["index"])] = row["art_style_id"]
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description="화풍 예시 전달본 생성 (C4)")
    parser.add_argument(
        "--traits",
        nargs="*",
        type=int,
        default=list(TRAITS_BY_DEFAULT),
        help="특징 포함본을 넘길 화풍 번호. 값 없이 주면 전부 이름만",
    )
    parser.add_argument("--quality", type=int, default=WEBP_QUALITY)
    args = parser.parse_args()

    with_traits = set(args.traits)
    unknown = with_traits - {style.index for style in styles.ART_STYLES}
    if unknown:
        raise SystemExit(f"없는 화풍 번호입니다: {sorted(unknown)}")

    plain_ids = _art_style_ids(with_traits=False)
    traits_ids = _art_style_ids(with_traits=True)

    HANDOFF.mkdir(parents=True, exist_ok=True)
    rows = []
    entries = []
    saved = 0
    original = 0

    for style in styles.ART_STYLES:
        traits = style.index in with_traits
        source = SOURCE / (f"{style.slug}-traits.png" if traits else f"{style.slug}.png")
        if not source.exists():
            raise SystemExit(f"원본이 없습니다: {source.name}")

        buffer = io.BytesIO()
        with Image.open(source) as image:
            image.convert("RGB").save(buffer, "WEBP", quality=args.quality, method=6)
        payload = buffer.getvalue()

        target = HANDOFF / f"{style.slug}.webp"
        target.write_bytes(payload)
        original += source.stat().st_size
        saved += len(payload)

        art_style_id = (traits_ids if traits else plain_ids)[style.index]
        rows.append(
            {
                "index": style.index,
                "name": style.name,
                "art_style_id": art_style_id,
                "condition": "특징 포함" if traits else "이름만",
                "file": target.name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        entries.append(
            {"artStyleId": art_style_id, "name": style.name, "exampleImageUrl": ""}
        )

    with (HANDOFF / "handoff.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # 05 가 그대로 복사할 수 있는 형태로 남깁니다. 순서는 판정 시트 회차 / 기획서 12.2 격자 /
    # 03-AI_생성_서빙.md 정본 표와 같아야 하고, 이 파일은 그 정본의 사본인 styles.py 순서를
    # 따릅니다.
    config = HANDOFF / "ADGEN_ART_STYLES.json"
    config.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"전달본: {HANDOFF}")
    print(f"  이미지 8장 {original / 1024 / 1024:.1f}MB -> {saved / 1024 / 1024:.1f}MB (WebP)")
    print(f"  특징 포함: {sorted(with_traits) or '없음'} / 나머지는 이름만")
    print(f"  {config.name} 의 exampleImageUrl 은 비어 있습니다 - 서빙 경로가 정해지면 채웁니다")
    print(
        "\n⚠️ 조건 선택은 판정 다수결에서 나온 **제안**이지 확정이 아닙니다. "
        "값이 정해지면 `--traits` 로 다시 만드세요."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

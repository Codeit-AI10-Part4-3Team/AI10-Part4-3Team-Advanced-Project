"""판정이 고른 예시 8장을 05 에게 넘길 형태로 만듭니다 (C4).

    python prepare_handoff.py                 # 확정값대로 (1 만 특징 포함)
    python prepare_handoff.py --traits 1 6    # 1 과 6 을 특징 포함으로
    python prepare_handoff.py --traits        # 전부 이름만

**값과 서빙 경로가 2026-08-22 에 확정됐습니다** (PR #194 코멘트, 05 임동규). `artStyleId` 는
판정 제안 그대로(1 만 특징 포함), 서빙은 **backend 정적 마운트**이고 파일은 VM `adgen-state`
볼륨의 `/data/art-styles/` 에 둡니다. `--traits` 는 값이 다시 바뀔 때를 위해 남겨 둡니다.

**`art_style_id` 는 손으로 적지 않습니다.** 이미지를 실제로 만든 문자열을 `manifest.csv` /
`manifest-traits.csv` 에서 그대로 읽어 옵니다. 옮겨 적다 한 글자가 틀리면 사용자가 본 예시와
실제 결과가 다른 프롬프트에서 나옵니다(`render_prompt._common_head` 의 `화풍은 {...}.`).

**PNG 를 그대로 넘기지 않습니다.** 원본은 장당 약 2MB 라 8장이면 15MB 가 넘고, 그것이 화풍
선택 화면 한 번에 전부 내려갑니다. 크기는 1152 px 그대로 두고 WebP 로만 다시 인코딩하면
합계가 약 1MB 로 줄어듭니다. 해상도를 깎지 않는 이유는 확대 보기(`.art-zoom`, 최대 560 CSS px)
가 고밀도 화면에서 두 배를 쓰기 때문이고, 파일이 하나인 이유는 계약의 `ArtStyle` 에
`exampleImageUrl` 이 하나뿐이기 때문입니다.

**파일 이름은 원본 것을 그대로 씁니다** - 1번만 `-traits` 가 붙습니다. 가지런히 고치고 싶은
자리지만, 그 접미어가 **`artStyleId` 가 1번만 다른 것과 같은 사실**을 가리킵니다. 지우면
나중에 "이 그림이 어느 조건이었나" 를 다시 물어야 합니다(05 제안, 2026-08-22). URL 도 이
이름을 정규화 없이 그대로 씁니다 - 설정에 문자열로 박히는 값이라 규칙에서 유도되지 않아
정규화의 이득이 없고, 파일명과 URL 이 같은 문자열이라야 눈으로 대조됩니다.
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

URL_PREFIX = "/static/art-styles"
"""`exampleImageUrl` 앞에 붙는 경로. 2026-08-22 에 05 가 정한 정적 마운트 지점입니다.

⚠️ **마운트 대상은 `/data` 가 아니라 `/data/art-styles` 여야 합니다.** 한 단계 위를 가리키면
같은 볼륨의 `adgen.sqlite` 와 사용자 업로드 사진이 인증 없이 열립니다 - 정적 마운트에는 라우트
의존성이 걸리지 않아 backend 의 나머지와 달리 인증 뒤에 있지 않습니다. 이 경고의 소관은
05(`apps/backend`)이고, 여기서는 URL 을 그 약속대로 적기만 합니다.
"""

TRAITS_BY_DEFAULT = (1,)
"""특징 포함으로 넘길 화풍 번호. 2026-08-22 확정값입니다.

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


def _plan(with_traits: set[int]) -> list[tuple[styles.ArtStyle, bool, str, Path]]:
    """이번 회차에 쓸 원본 8장을 **지우기 전에** 전부 확인합니다.

    정리가 검증보다 먼저면, 일부 화풍만 `--traits` 로 다시 돌리다 원본이 없는 조합을
    지정했을 때 이전 회차를 다 지운 뒤 중간에 멈춥니다. 8장도 9장도 아닌 폴더가 남고,
    그것은 아래 정리가 막으려던 것과 같은 모양의 사고입니다 (PR #205 리뷰).
    """
    plan = []
    for style in styles.ART_STYLES:
        traits = style.index in with_traits
        # 원본 이름을 그대로 물려받습니다 (1번만 `-traits`). 접미어가 조건을 가리키므로
        # 여기서 가지런히 고치면 그 사실이 사라집니다 - 자세한 이유는 파일 상단.
        stem = f"{style.slug}-traits" if traits else style.slug
        source = SOURCE / f"{stem}.png"
        if not source.exists():
            raise SystemExit(f"원본이 없습니다: {source.name}")
        plan.append((style, traits, stem, source))
    return plan


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
    parser.add_argument(
        "--url-prefix",
        default=URL_PREFIX,
        help="exampleImageUrl 앞에 붙는 경로 (기본: 05 가 정한 정적 마운트 지점)",
    )
    args = parser.parse_args()

    with_traits = set(args.traits)
    unknown = with_traits - {style.index for style in styles.ART_STYLES}
    if unknown:
        raise SystemExit(f"없는 화풍 번호입니다: {sorted(unknown)}")

    plain_ids = _art_style_ids(with_traits=False)
    traits_ids = _art_style_ids(with_traits=True)

    plan = _plan(with_traits)

    HANDOFF.mkdir(parents=True, exist_ok=True)

    # ⚠️ 덮어쓰기만 하면 **직전 회차의 파일이 남습니다.** 조건이나 이름 규칙이 바뀌면 지난
    # 이름의 파일이 그대로 남아 8장이어야 할 폴더가 9장이 되고, 받는 쪽은 어느 것이 이번
    # 것인지 알 수 없습니다. 실제로 `style-01.webp`(이름만처럼 보이는 특징 포함본)가 그렇게
    # 남았습니다. 지우는 대상은 이 스크립트가 만드는 것뿐입니다.
    for pattern in ("*.webp", "ADGEN_ART_STYLES*.json", "handoff.csv"):
        for path in HANDOFF.glob(pattern):
            path.unlink()

    rows = []
    empty_entries = []
    filled_entries = []
    saved = 0
    original = 0

    for style, traits, stem, source in plan:
        buffer = io.BytesIO()
        with Image.open(source) as image:
            image.convert("RGB").save(buffer, "WEBP", quality=args.quality, method=6)
        payload = buffer.getvalue()

        target = HANDOFF / f"{stem}.webp"
        target.write_bytes(payload)
        original += source.stat().st_size
        saved += len(payload)

        art_style_id = (traits_ids if traits else plain_ids)[style.index]
        url = f"{args.url_prefix.rstrip('/')}/{target.name}"
        rows.append(
            {
                "index": style.index,
                "name": style.name,
                "art_style_id": art_style_id,
                "condition": "특징 포함" if traits else "이름만",
                "file": target.name,
                "example_image_url": url,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        base = {"artStyleId": art_style_id, "name": style.name}
        empty_entries.append({**base, "exampleImageUrl": ""})
        filled_entries.append({**base, "exampleImageUrl": url})

    with (HANDOFF / "handoff.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # 05 가 그대로 복사할 수 있는 형태로 남깁니다. 순서는 판정 시트 회차 / 기획서 12.2 격자 /
    # 03-AI_생성_서빙.md 정본 표와 같아야 하고, 이 파일은 그 정본의 사본인 styles.py 순서를
    # 따릅니다.
    #
    # 두 벌인 이유는 05 가 두 단계로 넣기로 했기 때문입니다. 파일이 볼륨에 들어가기 전에
    # URL 을 채우면 `<img>` 가 404 를 그립니다 - 빈 문자열이면 `ArtStylePicker` 가 "예시
    # 준비 중" 자리를 잡으므로(#179), 순서를 뒤집으면 화면이 더 나빠집니다.
    stage1 = HANDOFF / "ADGEN_ART_STYLES.json"
    stage2 = HANDOFF / "ADGEN_ART_STYLES.filled.json"
    for path, payload_entries in ((stage1, empty_entries), (stage2, filled_entries)):
        path.write_text(
            json.dumps(payload_entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"전달본: {HANDOFF}")
    print(f"  이미지 8장 {original / 1024 / 1024:.1f}MB -> {saved / 1024 / 1024:.1f}MB (WebP)")
    print(f"  특징 포함: {sorted(with_traits) or '없음'} / 나머지는 이름만")
    print(f"  {stage1.name}: URL 이 빈 문자열 - 파일을 볼륨에 넣기 전에 쓰는 1단계본")
    print(f"  {stage2.name}: URL 이 {args.url_prefix} 로 채워진 2단계본")
    print(
        "\n⚠️ 파일을 볼륨에 넣기 전에 2단계본을 넣으면 카드가 404 를 그립니다. "
        "빈 문자열이면 '예시 준비 중' 자리가 잡힙니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

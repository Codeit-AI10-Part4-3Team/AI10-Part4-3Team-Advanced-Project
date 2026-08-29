"""제품 사진을 레퍼런스로 넘겼을 때 무슨 일이 생기는가 (구현 전 1회 탐색).

    python run_probe.py                 # 프롬프트만 출력. 요금 없음
    python run_probe.py --yes           # 실제 호출 1회 (약 0.007 USD)

⚠️ **이것은 구현이 아니라 미지수를 사는 회차입니다.** 계약도 backend 도 건드리지 않고, 지금
코드가 이미 가진 경로(`render._generate` 의 `reference`)에 **제품 사진**을 넣어 봅니다. 답을
원하는 물음은 넷입니다.

1. 사진을 주면 제품이 실제로 반영되는가 (S01 은 트레포일 로고가 하얗게 날아갔습니다)
2. 화풍 지시가 사진의 질감을 이기는가 (`edit` 이 입력 이미지의 사실성을 끌고 올 수 있습니다)
3. 라벨과 로고의 작은 글자, 인증 마크가 새어 나오는가 (근거 밖 주장이 그림에 들어가는 자리)
4. 우리 호출 모양(`_generate` 의 kwargs, inline base64)이 그대로 도는가

⚠️ **`test_` 로 시작하지 않습니다.** `apps/ai-engine` 의 pytest 가 `eval/` 과 함께 이 계열을
수집하면 CI 가 외부 API 를 부릅니다 (AGENTS.md). 실행 스크립트는 `run_*.py` 입니다.

⚠️ **결과물은 커밋하지 않습니다.** 저장소가 public 이고 제품 사진은 타인의 상업 사진입니다.
출력은 `outputs/`(gitignore 142번 줄)로만 나갑니다.

조건 선택은 무작위이고 시드를 함께 적습니다 (SEED=42, 아래 `_draw`). 재현 불가능한 결과는
실험 자료가 아니라는 규칙(CLAUDE.md)을 이 회차도 따릅니다.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_engine import render, render_prompt
from ai_engine.config import Settings
from ai_engine.models import (
    PANEL_ROLES,
    Brief,
    ComicDraft,
    ImageRenderRequest,
    ImageSpec,
    Panel,
    SingleAdDraft,
)

SEED = 42

REPO = Path(__file__).resolve().parents[3]
PHOTO_DIR = REPO / "outputs" / "API_이미지생성_검증" / "테스트이미지"
OUT_DIR = REPO / "outputs" / "API_이미지생성_검증" / "제품사진_레퍼런스_탐색"

KEEP_PRODUCT_PHOTO = (
    "입력으로 준 사진에 나온 제품을 그린다. 제품의 색, 형태, 로고와 라벨의 배치가 사진과 "
    "같아야 한다. 사진을 그대로 붙여 넣지 말고 아래 화풍으로 다시 그린다. 라벨 안의 인증 "
    "마크, 성분표, 작은 글자는 그리지 않는다."
)
"""이번 회차가 재는 문장입니다. 통과하면 `render_prompt` 로 승격합니다.

⚠️ 세 요구가 한 문장에 들어 있고 **서로 당깁니다** - 사진과 같게(1), 그러나 화풍으로(2),
그러나 글자는 빼고(3). 어느 쪽이 이기는지가 이 회차의 관측입니다.

⚠️ 인증 마크와 성분표를 막는 것은 미관 때문이 아닙니다. 근거(`sellingPoint` + `note` +
제품명)에 없는 인증 주장이 그림에 들어가면 카피 쪽에서 막아 둔 것(INV-6)이 이미지로 새어
나가고, 우리 검출기는 이미지 안의 글자를 보지 못합니다.
"""

# `docs/보고서/실물모드_시나리오_테스트_계획서.md` C-b 표의 값을 그대로 씁니다. 여기서 새로
# 지어내면 08-29 회차와 다른 입력이 되어 비교가 성립하지 않습니다.
PRODUCTS: dict[str, dict[str, str]] = {
    "원더로스팅원두블랜딩홀빈커피원두.jpg": {
        "product_name": "원더로스팅 블렌딩 홀빈 원두 1kg",
        "selling_point": (
            "블렌딩 원두를 분쇄하지 않은 홀빈 상태로 담았습니다. 1kg 한 봉지이고 중배전이라 "
            "산미와 단맛이 함께 납니다. 그라인더로 갈아 씁니다."
        ),
        "note": "집에서 커피를 내려 마시는 30대가 주 타겟입니다. 아침 햇살이 드는 조용한 카페 분위기로 부탁합니다.",
        "category": "식품",
        "target": "30대",
    },
    "adidas야구모자워시드.webp": {
        "product_name": "아디다스 워시드 야구 모자",
        "selling_point": (
            "워시드 가공한 면 소재 볼캡입니다. 앞면에 트레포일 로고가 자수로 들어가 있고 "
            "뒤쪽 스트랩으로 머리 둘레를 조절합니다. 연하늘색 한 가지입니다."
        ),
        "note": "캠퍼스를 오가는 20대 대학생이 주 타겟입니다. 주인공으로 나오면 좋겠습니다.",
        "category": "패션 잡화",
        "target": "20대 대학생",
    },
}

ART_STYLES: dict[int, str] = {
    # 1번만 특징을 함께 싣습니다 (2026-08-22 확정, `verify05_art_styles/styles.py`).
    1: "심플 플랫 웹툰 (굵은 선, 단순한 색, 풍부한 표정)",
    2: "한국형 일상 웹툰",
    3: "SD 캐릭터, 치비",
    4: "레트로 팝아트",
    5: "감성 수채화",
    6: "세련된 에디토리얼",
    7: "3D 클레이 캐릭터",
    8: "시네마틱 애니메이션",
}


def _draw() -> tuple[str, int]:
    """사진 하나와 화풍 하나를 무작위로. 시드가 고정이라 같은 조합이 다시 나옵니다."""
    rng = random.Random(SEED)
    photos = sorted(path.name for path in PHOTO_DIR.glob("*") if path.suffix != ".md")
    return rng.choice(photos), rng.choice(sorted(ART_STYLES))


def _request(photo: str, style_index: int) -> ImageRenderRequest:
    """단일 광고형 1장. **시안은 손으로 씁니다.**

    `draft:generate` 를 부르면 텍스트 요금(0.0277 USD)이 더 들고, 카피가 회차마다 달라져
    "그림이 달라진 이유"가 둘이 됩니다. 이 회차의 물음은 렌더 이음매 하나입니다.
    """
    product = PRODUCTS[photo]
    return ImageRenderRequest(
        output_type="single_ad",
        brief=Brief.model_validate(
            {
                "productImageUrl": "/v1/sessions/probe/image",
                "productName": product["product_name"],
                "sellingPoint": product["selling_point"],
                "note": product["note"],
                "category": product["category"],
                "target": product["target"],
                "artStyle": ART_STYLES[style_index],
            }
        ),
        draft=SingleAdDraft(
            ad_plan="캠퍼스를 오가는 하루에 모자를 얹어 보여 주는 한 장입니다.",
            ad_copy="오늘도 캠퍼스, 모자 하나면 충분",
            visual_plan=(
                "강의동 앞 계단에 앉은 대학생이 연하늘색 볼캡을 쓰고 있는 장면. "
                "모자가 화면 가운데에서 크게 보이도록 배치한다."
            ),
        ),
        spec=ImageSpec(width=1024, height=1024),
        quality="low",
    )


COMIC_PANELS: tuple[tuple[str, str], ...] = (
    ("창가 원목 테이블에 원두 봉투가 놓여 있고, 머그를 든 인물이 창밖을 보는 장면", "오늘은 원더로스팅이야."),
    ("같은 테이블에서 인물이 턱을 괴고 앉아 있는 장면", "집이 카페 같았으면."),
    ("인물이 빈 머그를 내려다보며 고민하는 장면", "무얼 갈아 마실까?"),
    ("인물이 테이블에 놓인 원두 봉투를 손으로 가리키는 장면", "바로 이 블렌딩 홀빈!"),
    ("인물이 그라인더에 원두를 넣고 가는 장면", "산미와 단맛이 함께."),
    ("인물이 커피를 마시며 만족스러워하는 장면", "매일 이 맛, 지금 담자."),
)
"""2차 회차의 6칸. **1번 칸만 실제로 그립니다** - 나머지는 계약이 6칸을 요구해서 채웁니다.

08-29 회차의 S04 결과물에서 읽은 장면과 대사를 그대로 옮겼습니다. 새로 지어내면 "그림이
달라진 이유"가 사진 말고도 하나 더 생깁니다.
"""


def _comic_request(photo: str, style_index: int) -> ImageRenderRequest:
    """만화형 1번 칸 조건. 티어와 크기가 단일 광고형과 다릅니다 (medium, 1152).

    ⚠️ `with_reference=False` 로 부릅니다. 그 인자가 붙이는 `KEEP_REFERENCE` 는 "인물과
    제품과 배경을 그대로 유지한다" 인데, 지금 레퍼런스는 인물도 배경도 없는 제품 사진입니다.
    그 문장을 붙이면 모델이 사진의 흰 배경을 배경으로 삼습니다 - 구현할 때 이 자리가
    참/거짓이 아니라 **레퍼런스 3갈래**가 되어야 하는 이유입니다.
    """
    product = PRODUCTS[photo]
    return ImageRenderRequest(
        output_type="comic",
        brief=Brief.model_validate(
            {
                "productImageUrl": "/v1/sessions/probe/image",
                "productName": product["product_name"],
                "sellingPoint": product["selling_point"],
                "note": product["note"],
                "category": product["category"],
                "target": product["target"],
                "artStyle": ART_STYLES[style_index],
                "character": {"appearance": "20대 후반 여성, 머리를 위로 묶음", "outfit": "크림색 니트"},
            }
        ),
        draft=ComicDraft(
            ad_plan="집에서 카페 같은 한 잔을 내리는 하루를 여섯 칸으로 보여 줍니다.",
            panels=[
                Panel(index=index, role=role, scene=scene, dialogue=dialogue)
                for index, (role, (scene, dialogue)) in enumerate(
                    zip(PANEL_ROLES, COMIC_PANELS, strict=True), start=1
                )
            ],
        ),
        spec=ImageSpec(width=3456, height=2304),
        quality="medium",
    )


def _prompt(request: ImageRenderRequest) -> str:
    """레퍼런스 지시를 **앞에** 둡니다 - `build_panel` 이 `KEEP_REFERENCE` 를 두는 자리와
    같습니다. 구현할 때도 같은 자리에 들어갑니다."""
    if isinstance(request.draft, ComicDraft):
        panel = request.draft.panels[0]
        body = render_prompt.build_panel(request, panel, with_reference=False)
    else:
        body = render_prompt.build(request)
    return f"{KEEP_PRODUCT_PHOTO}\n{body}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="실제로 호출합니다 (요금 발생)")
    parser.add_argument("--comic", action="store_true", help="만화형 1번 칸 조건 (medium, 1152)")
    parser.add_argument("--photo", help="무작위 대신 이 사진으로")
    parser.add_argument("--style", type=int, help="무작위 대신 이 화풍 번호로")
    args = parser.parse_args()

    drawn_photo, drawn_style = _draw()
    photo = args.photo or drawn_photo
    style_index = args.style or drawn_style
    photo_path = PHOTO_DIR / photo
    if not photo_path.is_file():
        return _fail(f"사진이 없습니다: {photo_path}")
    if photo not in PRODUCTS:
        return _fail(f"제품 정보가 없습니다: {photo}")

    request = _comic_request(photo, style_index) if args.comic else _request(photo, style_index)
    prompt = _prompt(request)
    if args.comic:
        width, height = render._panel_size(request.spec)
    else:
        width, height = request.spec.width, request.spec.height

    drawn = "무작위" if not (args.photo or args.style) else "지정"
    print(f"[조건] SEED={SEED}({drawn}) / 사진={photo} / 화풍 {style_index}={ART_STYLES[style_index]}")
    print(
        f"[조건] 유형={'만화형 1번 칸' if args.comic else '단일 광고형'} / "
        f"티어={request.quality} / 규격={width}x{height} / 모델={Settings().image_model}"
    )
    print(f"[사진] {photo_path} ({photo_path.stat().st_size:,} bytes)")
    print("-" * 78)
    print(prompt)
    print("-" * 78)

    if not args.yes:
        print("[중단] --yes 가 없어 호출하지 않았습니다. 요금 0.")
        return 0

    key = os.environ.get("ADGEN_MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return _fail("ADGEN_MODEL_API_KEY 가 없습니다.")

    settings = Settings(generation_mode="model", model_api_key=key)
    client = render._client(settings)
    reference = photo_path.read_bytes()

    started = datetime.now()
    payload = render._generate(
        client,
        settings,
        prompt=prompt,
        size=f"{width}x{height}",
        quality=request.quality,
        reference=reference,
    )
    elapsed = (datetime.now() - started).total_seconds()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    kind = "comic1" if args.comic else "single"
    image_path = OUT_DIR / f"{stamp}_{kind}_style{style_index:02d}_{Path(photo).stem}.png"
    image_path.write_bytes(payload)
    (OUT_DIR / f"{stamp}_manifest.json").write_text(
        json.dumps(
            {
                "seed": SEED,
                "photo": photo,
                "art_style_index": style_index,
                "art_style": ART_STYLES[style_index],
                "output_type": request.output_type,
                "quality": request.quality,
                "size": f"{width}x{height}",
                "image_model": settings.image_model,
                "prompt": prompt,
                "elapsed_s": round(elapsed, 1),
                "bytes": len(payload),
                "started_at": started.isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[완료] {elapsed:.1f}초 / {len(payload):,} bytes -> {image_path}")
    return 0


def _fail(message: str) -> int:
    print(f"[중단] {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

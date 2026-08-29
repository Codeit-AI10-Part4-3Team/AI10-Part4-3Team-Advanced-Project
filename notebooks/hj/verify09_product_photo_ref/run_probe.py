"""제품 사진을 레퍼런스로 넘겼을 때 무슨 일이 생기는가 (ADR-0022 탐색).

    python run_probe.py                          # 프롬프트만 출력. 요금 없음
    python run_probe.py --yes                    # 무작위 1조합 (단일 광고형 low, 약 0.007 USD)
    python run_probe.py --yes --comic            # 만화형 1번 칸 조건 (medium, 약 0.07 USD)
    python run_probe.py --yes --matrix           # 남은 사진 6장 x 남은 화풍 6종 (약 0.042 USD)
    python run_probe.py --yes --photo <파일> --style <번호>

⚠️ **이것은 구현이 아니라 미지수를 사는 회차입니다.** 답을 원하는 물음은 넷입니다.

1. 사진을 주면 제품이 실제로 반영되는가 (S01 은 트레포일 로고가 하얗게 날아갔습니다)
2. 화풍 지시가 사진의 질감을 이기는가 (`edit` 이 입력 이미지의 사실성을 끌고 올 수 있습니다)
3. 라벨과 로고의 작은 글자, 인증 마크가 새어 나오는가 (근거 밖 주장이 그림에 들어가는 자리)
4. 우리 호출 모양이 그대로 도는가

⚠️ **1차와 2차 이후로는 `render.render_image` 를 그대로 부릅니다.** 프롬프트를 손으로 조립하면
재는 대상이 우리 구현이 아니라 이 파일이 됩니다 - base64 해독(`_product_photo`), MIME 판정
(`_reference_part`), 레퍼런스 3갈래, 무손실 WebP 변환까지 전부 실제 경로를 지납니다.

⚠️ **`test_` 로 시작하지 않습니다.** `apps/ai-engine` 의 pytest 가 이 계열을 수집하면 CI 가
외부 API 를 부릅니다 (AGENTS.md). 실행 스크립트는 `run_*.py` 입니다.

⚠️ **결과물은 커밋하지 않습니다.** 저장소가 public 이고 제품 사진은 타인의 상업 사진입니다.
출력은 `outputs/`(gitignore 142번 줄)로만 나갑니다.

조건 선택은 무작위이고 시드를 함께 적습니다 (SEED=42). 재현 불가능한 결과는 실험 자료가
아니라는 규칙(CLAUDE.md)을 이 회차도 따릅니다.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

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

# `docs/보고서/실물모드_시나리오_테스트_계획서.md` C-b 표의 값을 그대로 씁니다. 여기서 새로
# 지어내면 08-29 회차와 다른 입력이 되어 비교가 성립하지 않습니다.
#
# ⚠️ 시안(`ad_copy`, `visual_plan`)은 **손으로 썼습니다.** `draft:generate` 를 부르면 텍스트
# 요금이 더 들고 카피가 회차마다 달라져 "그림이 달라진 이유"가 둘이 됩니다. 카피는 전부
# 소구점 안의 말로만 썼습니다 - 근거 밖 수치를 넣으면 이 회차가 가드레일 시험이 됩니다.
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
        "ad_plan": "아침 햇살이 드는 부엌에서 한 잔을 내리는 장면으로 보여 줍니다.",
        "ad_copy": "오늘 아침, 갈아 내린 한 잔",
        "visual_plan": "창가 원목 테이블에 원두 봉투와 머그를 놓고, 봉투가 화면 가운데에서 크게 보이게 배치한다.",
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
        "ad_plan": "캠퍼스를 오가는 하루에 모자를 얹어 보여 주는 한 장입니다.",
        "ad_copy": "오늘도 캠퍼스, 모자 하나면 충분",
        "visual_plan": (
            "강의동 앞 계단에 앉은 대학생이 연하늘색 볼캡을 쓰고 있는 장면. "
            "모자가 화면 가운데에서 크게 보이도록 배치한다."
        ),
    },
    "플렌느방향제실내용디퓨저블렉체리.webp": {
        "product_name": "플렌느 프리미엄 디퓨저 블랙체리",
        "selling_point": (
            "블랙체리 향의 실내용 리드 디퓨저입니다. 200ml 유리병에 리드 스틱 다섯 개가 "
            "들어 있고, 거실이나 침실에 두고 씁니다."
        ),
        "note": "혼자 사는 20대와 30대가 주 타겟입니다. 퇴근하고 집에 들어왔을 때의 편안한 분위기로 부탁합니다.",
        "category": "생활용품",
        "target": "20대와 30대 1인 가구",
        "ad_plan": "퇴근하고 문을 연 순간의 공기를 한 장에 담습니다.",
        "ad_copy": "집에 들어서면, 블랙체리",
        "visual_plan": "저녁 조명이 켜진 침실 협탁에 디퓨저를 놓고, 리드 스틱이 또렷하게 보이도록 배치한다.",
    },
    "한돈삼겹살.jpg": {
        "product_name": "한돈 삼겹살",
        "selling_point": (
            "국내산 돼지고기 삼겹살입니다. 5mm 두께로 썰어 구우면 기름이 빠르게 빠지고, "
            "500g 한 팩에 3 ~ 4인분이 들어 있습니다. 냉장으로 배송합니다."
        ),
        "note": "주말에 가족과 고기를 굽는 30대와 40대가 주 타겟입니다. 가족이 둘러앉은 식탁을 배경으로 해 주세요.",
        "category": "식품",
        "target": "30대와 40대 가족",
        "ad_plan": "주말 식탁에 둘러앉은 장면으로 보여 줍니다.",
        "ad_copy": "주말 식탁, 삼겹살 한 팩",
        "visual_plan": "가족이 둘러앉은 식탁 위 불판 옆에 제품 팩을 놓고, 팩이 화면 앞쪽에 크게 보이게 배치한다.",
    },
    "코카콜라.png": {
        "product_name": "코카콜라",
        "selling_point": (
            "유리병에 담은 콜라입니다. 350ml 용량이고 차게 두었다가 병째로 마시는 "
            "제품입니다. 탄산이 강해 식사와 함께 마시기 좋습니다."
        ),
        "note": "10대와 20대가 주 타겟입니다. 북극곰 캐릭터가 등장하게 해 주세요.",
        "category": "음료",
        "target": "10대와 20대",
        "ad_plan": "식사와 함께 병째로 마시는 순간을 한 장에 담습니다.",
        "ad_copy": "차게 두었다가, 병째로",
        "visual_plan": "식탁 위에 유리병 콜라를 세워 두고 물방울이 맺힌 병이 화면 가운데에 오게 배치한다.",
    },
    "델리메탈샤프펜슬.webp": {
        "product_name": "델리 메탈 샤프펜슬",
        "selling_point": (
            "금속 몸체의 0.5mm 노크식 샤프펜슬입니다. 무게중심이 아래쪽에 있어 오래 써도 "
            "손이 덜 피로하고, 흰색 분홍색 하늘색 세 가지가 있습니다."
        ),
        "note": "시험을 준비하는 10대와 20대 학생이 주 타겟입니다. 시험 기간에 집중하는 상황으로 부탁합니다.",
        "category": "문구",
        "target": "10대와 20대 학생",
        "ad_plan": "시험 기간의 책상 위를 한 장에 담습니다.",
        "ad_copy": "오래 써도 덜 피로한 손",
        "visual_plan": "필기 중인 노트 옆에 샤프펜슬을 놓고, 금속 몸체가 화면 앞쪽에서 또렷하게 보이게 배치한다.",
    },
    "비쿨미니휴대용선풍기.webp": {
        "product_name": "비쿨 미니 휴대용 선풍기",
        "selling_point": (
            "손에 쥐고 쓰는 휴대용 선풍기입니다. USB로 충전하고 풍량은 3단계이며, 민트 분홍 "
            "파랑 세 가지 색이 있습니다. 가방에 넣고 다닐 수 있는 크기입니다."
        ),
        "note": "야외 활동이 많은 20대와 30대가 주 타겟입니다. 더워서 선풍기를 꺼내 쐬는 장면으로 부탁합니다.",
        "category": "생활가전",
        "target": "20대와 30대",
        "ad_plan": "더운 날 야외에서 바람을 쐬는 순간을 한 장에 담습니다.",
        "ad_copy": "가방에서 꺼내는 3단계 바람",
        "visual_plan": "여름 햇빛 아래 벤치에 앉은 인물이 손에 쥔 선풍기를 얼굴 쪽으로 향하게 하고, 선풍기가 크게 보이도록 배치한다.",
    },
    "TREKSLR7AXS로드자전거.png": {
        "product_name": "트렉 SLR7 AXS 로드 자전거",
        "selling_point": (
            "카본 프레임 로드 자전거입니다. 무선 변속 구동계와 디스크 브레이크를 쓰고 높은 "
            "림의 에어로 휠이 들어갑니다. 장거리 주행과 업힐을 함께 염두에 둔 구성입니다."
        ),
        "note": "주말 라이딩을 즐기는 30대와 40대가 주 타겟입니다. 자전거를 타고 달리는 장면으로 부탁합니다.",
        "category": "스포츠 용품",
        "target": "30대와 40대",
        "ad_plan": "주말 라이딩의 한 장면으로 보여 줍니다.",
        "ad_copy": "주말 라이딩, 카본 프레임으로",
        "visual_plan": "이른 아침 도로 위에 자전거를 측면으로 세워 두고, 프레임과 휠 전체가 화면에 들어오게 배치한다.",
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

USED_PHOTOS = frozenset({"adidas야구모자워시드.webp", "원더로스팅원두블랜딩홀빈커피원두.jpg"})
USED_STYLES = frozenset({1, 5})
"""1차와 2차가 이미 쓴 조합. `--matrix` 는 **여기 없는 것만** 돕니다.

같은 사진이나 같은 화풍을 다시 사는 것은 새 정보가 아닙니다. 남은 사진 6장과 남은 화풍 6종을
1:1 로 짝지으면 여덟 제품과 여덟 화풍이 각각 한 번씩 지나갑니다.
"""


def _draw() -> tuple[str, int]:
    """사진 하나와 화풍 하나를 무작위로. 시드가 고정이라 같은 조합이 다시 나옵니다."""
    rng = random.Random(SEED)
    return rng.choice(sorted(PRODUCTS)), rng.choice(sorted(ART_STYLES))


def _matrix() -> list[tuple[str, int]]:
    """남은 사진과 남은 화풍의 1:1 짝. 순서는 시드가 정합니다."""
    photos = sorted(name for name in PRODUCTS if name not in USED_PHOTOS)
    styles = sorted(index for index in ART_STYLES if index not in USED_STYLES)
    random.Random(SEED).shuffle(styles)
    return list(zip(photos, styles, strict=True))


def _request(photo: str, style_index: int) -> ImageRenderRequest:
    """단일 광고형 1장 (`low`, 1024). 사진은 base64 로 요청에 실립니다 (ADR-0022)."""
    product = PRODUCTS[photo]
    return ImageRenderRequest(
        output_type="single_ad",
        brief=_brief(product, style_index),
        draft=SingleAdDraft(
            ad_plan=product["ad_plan"],
            ad_copy=product["ad_copy"],
            visual_plan=product["visual_plan"],
        ),
        spec=ImageSpec(width=1024, height=1024),
        quality="low",
        product_image=_encoded(photo),
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


def _comic_request(photo: str, style_index: int, quality: str = "medium") -> ImageRenderRequest:
    """만화형. 티어와 크기가 단일 광고형과 다릅니다 (medium, 칸당 1152).

    ⚠️ **여섯 칸을 다 그립니다** (약 0.43 USD). 1번 칸만 보고 싶으면 `--matrix` 쪽 티어로
    충분하고, 이 경로는 사진이 1번 칸에서 멈추는지까지 확인할 때만 씁니다.
    """
    product = PRODUCTS[photo]
    return ImageRenderRequest(
        output_type="comic",
        brief=_brief(
            product,
            style_index,
            character={"appearance": "20대 후반 여성, 머리를 위로 묶음", "outfit": "크림색 니트"},
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
        quality=quality,  # type: ignore[arg-type]
        product_image=_encoded(photo),
    )


def _brief(product: dict[str, str], style_index: int, **extra: object) -> Brief:
    return Brief.model_validate(
        {
            "productImageUrl": "/v1/sessions/probe/image",
            "productName": product["product_name"],
            "sellingPoint": product["selling_point"],
            "note": product["note"],
            "category": product["category"],
            "target": product["target"],
            "artStyle": ART_STYLES[style_index],
            **extra,
        }
    )


def _encoded(photo: str) -> str:
    return base64.b64encode((PHOTO_DIR / photo).read_bytes()).decode("ascii")


def _prompt_preview(request: ImageRenderRequest) -> str:
    """`--yes` 없이 볼 때만 씁니다. 실제 호출은 `render.render_image` 안에서 조립합니다."""
    if isinstance(request.draft, ComicDraft):
        return render_prompt.build_panel(
            request, request.draft.panels[0], reference="product_photo"
        )
    return render_prompt.build(request, reference="product_photo")


def _run(photo: str, style_index: int, *, comic: bool, quality: str, settings: Settings) -> Path:
    """한 조합을 실제로 그립니다. **구현 경로를 그대로 지납니다.**"""
    request = (
        _comic_request(photo, style_index, quality) if comic else _request(photo, style_index)
    )
    started = datetime.now()
    payload = render.render_image(request, settings)
    elapsed = (datetime.now() - started).total_seconds()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    kind = "comic" if comic else "single"
    image_path = OUT_DIR / f"{stamp}_{kind}_style{style_index:02d}_{Path(photo).stem}.webp"
    image_path.write_bytes(payload)
    image_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "seed": SEED,
                "photo": photo,
                "art_style_index": style_index,
                "art_style": ART_STYLES[style_index],
                "output_type": request.output_type,
                "quality": request.quality,
                "spec": f"{request.spec.width}x{request.spec.height}",
                "image_model": settings.image_model,
                "prompt": _prompt_preview(request),
                "elapsed_s": round(elapsed, 1),
                "bytes": len(payload),
                "started_at": started.isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  {elapsed:5.1f}초 {len(payload):>9,} bytes  -> {image_path.name}")
    return image_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="실제로 호출합니다 (요금 발생)")
    parser.add_argument("--comic", action="store_true", help="만화형 6칸 (medium 약 0.43 USD)")
    parser.add_argument(
        "--quality", default="medium", choices=("low", "medium"), help="만화형 티어"
    )
    parser.add_argument("--matrix", action="store_true", help="남은 사진 6장 x 남은 화풍 6종")
    parser.add_argument("--photo", help="무작위 대신 이 사진으로")
    parser.add_argument("--style", type=int, help="무작위 대신 이 화풍 번호로")
    args = parser.parse_args()

    if args.matrix:
        pairs = _matrix()
    else:
        drawn_photo, drawn_style = _draw()
        pairs = [(args.photo or drawn_photo, args.style or drawn_style)]

    for photo, style_index in pairs:
        if photo not in PRODUCTS:
            return _fail(f"제품 정보가 없습니다: {photo}")
        if not (PHOTO_DIR / photo).is_file():
            return _fail(f"사진이 없습니다: {PHOTO_DIR / photo}")

    tier = args.quality if args.comic else "low"
    print(
        f"[조건] SEED={SEED} / 조합 {len(pairs)}건 / "
        f"유형={'만화형 6칸' if args.comic else '단일 광고형'} / 티어={tier}"
    )
    for photo, style_index in pairs:
        print(f"  - {photo}  x  화풍 {style_index} {ART_STYLES[style_index]}")

    if not args.yes:
        print("-" * 78)
        preview = _comic_request(*pairs[0], args.quality) if args.comic else _request(*pairs[0])
        print(_prompt_preview(preview))
        print("-" * 78)
        print("[중단] --yes 가 없어 호출하지 않았습니다. 요금 0.")
        return 0

    key = os.environ.get("ADGEN_MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return _fail("ADGEN_MODEL_API_KEY 가 없습니다.")

    settings = Settings(generation_mode="model", model_api_key=key)
    failures = 0
    for photo, style_index in pairs:
        print(f"[생성] {photo} / 화풍 {style_index}")
        try:
            _run(photo, style_index, comic=args.comic, quality=args.quality, settings=settings)
        except render.RenderFailedError as exc:
            failures += 1
            print(f"  실패: {exc}", file=sys.stderr)

    print(f"[완료] {len(pairs) - failures}/{len(pairs)} 성공 -> {OUT_DIR}")
    return 1 if failures else 0


def _fail(message: str) -> int:
    print(f"[중단] {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

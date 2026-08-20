"""이미지 생성 프롬프트 조립. 모델 클라이언트와 분리해 둡니다.

⚠️ **FastAPI 도 모델 SDK 도 import 하지 않습니다.** 프롬프트가 맞는지는 호출 없이 확인할 수
있어야 합니다 - 한 번 부를 때마다 요금이 나가므로, 문장을 고칠 때마다 API 를 때리는 구조면
아무도 프롬프트를 손보지 않게 됩니다.

문장의 뼈대는 검증 1순위 하네스에서 왔습니다 - 만화형 칸은 `run_panels.py` 의 `panel_prompt`,
공통 문장은 `conditions.py` 입니다 (둘 다
`notebooks/hj/verify01_korean_text_rendering/`). 그 실험이 통과한 프롬프트와 실제 파이프라인의
프롬프트가 다르면 **실험 결과가 이전되지 않습니다** - 42회를 들여 잰 것이 지금 서비스가 쓰지
않는 문장이 됩니다. 실험 조건을 고칠 때 이 파일도 함께 보세요.
"""

from ai_engine.models import ComicDraft, Draft, ImageRenderRequest, Panel, SingleAdDraft

GROUNDING = "이 정보에 없는 효능, 수치, 성분, 수상 이력, 타사 비교를 이미지 안에 쓰지 않는다."
"""근거 기반 생성 (INV-6, AGENTS.md 설계 제약).

⚠️ **이 문장을 빼는 것은 프롬프트를 짧게 만드는 일이 아니라 가드레일을 끄는 일입니다.**
없는 효능을 그려 넣으면 표시광고법상 허위 과장 광고이고, 가드레일 on/off 델타 자체가 보고
지표라 우회하면 측정이 무효가 됩니다.
"""


def build(request: ImageRenderRequest) -> str:
    """단일 광고형 1장의 지시문.

    브리프와 시안 **양쪽**을 씁니다. 시안은 사용자가 이미 승인한 문장이므로 그림의 내용을
    결정하고, 브리프는 그 문장이 무엇에 근거했는지를 결정합니다 - 근거를 빼면 위의 제약을
    검사할 대상이 사라집니다.

    ⚠️ **만화형은 여기로 오지 않습니다.** 한 장에 6칸을 그리게 하는 프롬프트는 ADR-0017 이
    폐기한 방식이라 되살릴 자리를 남겨 두지 않았습니다 - 3456 / 3 = 1152 는 경계선과 바깥
    여백이 정확히 0 일 때만 성립하는데, 경계선을 그리라고 지시한 이상 칸은 반드시 1152px
    보다 작아집니다. 만화형은 `build_panel` 로 칸을 하나씩 만들어 합성합니다.
    """
    if isinstance(request.draft, ComicDraft):
        raise TypeError(
            "만화형은 build() 로 한 장을 통째로 그리지 않습니다 (ADR-0017). "
            "칸마다 build_panel() 을 쓰고 ai_engine.render 가 3x2 로 합성합니다."
        )
    return _single_ad(request, request.draft)


def _common_head(request: ImageRenderRequest) -> str:
    brief = request.brief
    lines = [
        f"화풍은 {brief.art_style}.",
        f"제품은 '{brief.product_name}'이고 소구점은 '{brief.selling_point}'이다.",
    ]
    # ⚠️ 빈 문자열은 "비어 있음"이고 키 생략은 "해당 없음"입니다 (계약 3절). 둘 다 프롬프트에
    # 넣지 않지만, `or` 한 번으로 합쳐 두면 나중에 의미가 갈릴 때 여기가 먼저 틀립니다.
    if brief.note:
        lines.append(f"추가 요청: {brief.note}")
    lines.append(GROUNDING)
    return "\n".join(lines)


def _single_ad(request: ImageRenderRequest, draft: SingleAdDraft) -> str:
    """단일 광고형 1장.

    ⚠️ `visualPlan` 이 그림의 지시문이고 `copy` 는 **이미지 안에 쓸 글자**입니다. 둘을 합쳐
    보내면 모델이 기획 문장을 그림에 써 넣습니다.
    """
    return (
        f"{_common_head(request)}\n"
        f"{request.spec.width} x {request.spec.height} 픽셀의 광고 이미지 1장을 그린다.\n"
        f"화면 구성: {draft.visual_plan}\n"
        f"이미지 안에 아래 문구를 오탈자 없이 정확히 그대로 표기한다. 글자를 임의로 바꾸거나 "
        f'줄이지 않는다.\n"{draft.ad_copy}"'
    )


SINGLE_PANEL = "정사각형 만화 한 칸. 격자나 여러 칸으로 나누지 않는다. 한 장면만 그린다."
"""⚠️ **합성이 격자를 만듭니다.** 이 문장이 빠지면 모델이 한 칸 안에 또 격자를 그려 넣고,
그러면 3x2 로 붙였을 때 36칸짜리 그림이 나옵니다. 실험 하네스의 `PANEL_PROMPT_HEAD` 와 같은
문장입니다 (`notebooks/hj/verify01_korean_text_rendering/run_panels.py`)."""

KEEP_REFERENCE = (
    "입력으로 준 이미지에 나온 인물과 제품을 그대로 유지한다. 얼굴, 머리 모양, 복장, "
    "제품 패키지의 색과 문구가 같아야 한다. 장면과 동작만 아래 지시대로 바꾼다."
)
"""2 ~ 6번 칸에만 붙습니다. 1번 칸은 레퍼런스가 될 그림 자체라 붙일 대상이 없습니다.

⚠️ **인물은 유지되지만 장면의 상태는 유지되지 않습니다** (2026-08-20 판정, 미결정_대장 A-4).
닦아낸 커피가 다음 칸에서 다시 쏟아지고 책상 길이가 바뀐 사례가 나왔습니다. 이 문장을 고쳐서
해결되는 종류가 아니므로 - 레퍼런스는 1번 칸 하나뿐이고 그 안에 "닦은 뒤"라는 상태가 없습니다 -
여기에 상태 관련 지시를 덧붙이지 마세요. 검증 3순위 판정 시트가 이 축을 묻도록 고치는 것이
먼저입니다.
"""


def build_panel(request: ImageRenderRequest, panel: Panel, *, with_reference: bool) -> str:
    """만화형 **한 칸**의 지시문. 칸마다 한 번씩 호출되고 결과를 우리가 3x2 로 붙입니다.

    ⚠️ 칸 크기를 지시문에 쓰지 않습니다. 크기는 API 요청의 `size` 가 정하고 그 값은
    `request.spec` 에서 나눠 나옵니다 - 문장에도 적으면 기획서 10.2 의 숫자가 두 곳에 생기고,
    한쪽만 고치는 순간 어긋납니다 (미결정_대장 N16 과 같은 이유).

    문장의 뼈대는 실험 하네스의 `panel_prompt` 입니다. **한 곳만 다릅니다** - 브리프의
    `character` 를 함께 보냅니다. 실험은 시나리오가 고정이라 인물 묘사가 장면 문장 안에 있었지만,
    운영 경로에서는 1번 칸에 인물을 알려 줄 통로가 이 필드뿐입니다 (레퍼런스가 없는 유일한 칸).
    """
    lines = [SINGLE_PANEL, f"전체 6칸 중 {panel.index}번 칸이다."]
    if with_reference:
        lines.append(KEEP_REFERENCE)
    lines.append(_common_head(request))
    if request.brief.character is not None:
        character = request.brief.character
        lines.append(f"등장인물의 외모는 {character.appearance}, 복장은 {character.outfit}.")
    lines.append(f"장면: {panel.scene}.")
    lines.append(
        f'말풍선을 하나 그리고 그 안에 "{panel.dialogue}" 를 오탈자 없이 정확히 그대로 '
        "표기한다. 글자를 임의로 바꾸거나 줄이지 않는다. 그 밖의 문구는 이미지에 넣지 않는다."
    )
    return "\n".join(lines)


def dialogue_of(draft: Draft) -> list[str]:
    """이미지 안에 그려질 문자열 전부. 가드레일 검사와 테스트가 씁니다."""
    if isinstance(draft, ComicDraft):
        return [panel.dialogue for panel in draft.panels]
    return [draft.ad_copy]

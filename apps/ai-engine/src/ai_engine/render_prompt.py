"""이미지 생성 프롬프트 조립. 모델 클라이언트와 분리해 둡니다.

⚠️ **FastAPI 도 모델 SDK 도 import 하지 않습니다.** 프롬프트가 맞는지는 호출 없이 확인할 수
있어야 합니다 - 한 번 부를 때마다 요금이 나가므로, 문장을 고칠 때마다 API 를 때리는 구조면
아무도 프롬프트를 손보지 않게 됩니다.

문장의 뼈대는 검증 1순위 하네스
(`notebooks/hj/verify01_korean_text_rendering/conditions.py`)에서 왔습니다. 그 실험이 통과한
프롬프트와 실제 파이프라인의 프롬프트가 다르면 **실험 결과가 이전되지 않습니다** - 20회를
들여 잰 것이 지금 서비스가 쓰지 않는 문장이 됩니다. 실험 조건을 고칠 때 이 파일도 함께
보세요.
"""

from ai_engine.models import ComicDraft, Draft, ImageRenderRequest, SingleAdDraft

GROUNDING = "이 정보에 없는 효능, 수치, 성분, 수상 이력, 타사 비교를 이미지 안에 쓰지 않는다."
"""근거 기반 생성 (INV-6, AGENTS.md 설계 제약).

⚠️ **이 문장을 빼는 것은 프롬프트를 짧게 만드는 일이 아니라 가드레일을 끄는 일입니다.**
없는 효능을 그려 넣으면 표시광고법상 허위 과장 광고이고, 가드레일 on/off 델타 자체가 보고
지표라 우회하면 측정이 무효가 됩니다.
"""


def build(request: ImageRenderRequest) -> str:
    """이 요청 하나로 그릴 그림의 지시문.

    브리프와 시안 **양쪽**을 씁니다. 시안은 사용자가 이미 승인한 문장이므로 그림의 내용을
    결정하고, 브리프는 그 문장이 무엇에 근거했는지를 결정합니다 - 근거를 빼면 위의 제약을
    검사할 대상이 사라집니다.
    """
    if isinstance(request.draft, ComicDraft):
        return _comic(request, request.draft)
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


def _comic(request: ImageRenderRequest, draft: ComicDraft) -> str:
    """만화형 1장 안에 6칸.

    ⚠️ **한 장 안의 격자입니다.** 컷을 6장으로 나눠 뽑는 경로는 아직 없습니다 - 컷 경계
    제어가 검증되지 않았고(검증 2순위, 미결정_대장 A-2), 그 결과에 따라 출력이 1장에서
    6장으로 바뀌면 계약의 응답 모양부터 달라집니다.

    ⚠️ 칸 크기는 `spec` 에서 나눠 계산하지 않고 요청한 전체 크기만 알립니다. 기획서 10.2 의
    숫자를 여기서 다시 계산하면 그 값이 두 곳에 생기고, 한쪽만 고치는 순간 어긋납니다
    (미결정_대장 N16 과 같은 이유).
    """
    panels = "\n".join(
        f'{panel.index}번 칸: {panel.scene}. 말풍선 대사: "{panel.dialogue}"'
        for panel in draft.panels
    )
    return (
        f"{_common_head(request)}\n"
        f"{request.spec.width} x {request.spec.height} 픽셀의 이미지 하나 안에 "
        f"3 x 2 격자로 정확히 6개의 칸을 그린다. 각 칸은 균등하게 나누고, 칸 사이에는 굵기가 "
        "일정한 흰색 경계선을 둔다. 칸의 순서는 왼쪽 위에서 오른쪽으로 읽는다.\n"
        "같은 인물이 모든 칸에서 동일한 얼굴과 복장으로 등장해야 한다.\n"
        "각 칸에 말풍선을 그리고 아래 한국어 대사를 오탈자 없이 정확히 그대로 표기한다. "
        f"글자를 임의로 바꾸거나 줄이지 않는다.\n\n{panels}"
    )


def dialogue_of(draft: Draft) -> list[str]:
    """이미지 안에 그려질 문자열 전부. 가드레일 검사와 테스트가 씁니다."""
    if isinstance(draft, ComicDraft):
        return [panel.dialogue for panel in draft.panels]
    return [draft.ad_copy]

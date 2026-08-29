"""`draft:generate` 와 `draft:patch` 의 프롬프트 조립. 모델 클라이언트와 분리해 둡니다.

⚠️ **FastAPI 도 모델 SDK 도 import 하지 않습니다** (`render_prompt` 와 같은 이유). 프롬프트가
맞는지는 호출 없이 확인할 수 있어야 하고, 한 번 부를 때마다 요금이 나가는 구조에서 문장을
고칠 때마다 API 를 때려야 한다면 아무도 프롬프트를 손보지 않게 됩니다.

조립 순서는 생성_파이프라인 4절의 표 그대로입니다 (역할 지시 -> 표현 가이드라인과 금지 사항 ->
제품 정보 -> 추론 결과 -> 화풍 -> 유형별 지시 -> 출력 규격). **순서를 바꾸지 마세요** - 그
표가 프롬프트의 정본이고, 코드가 표와 달라지는 순간 문서가 프롬프트를 설명하지 못합니다.
"""

from ai_engine.models import (
    PANEL_ROLES,
    Brief,
    ComicDraft,
    DraftGenerateRequest,
    DraftPatch,
    DraftPatchEngineRequest,
    PanelRole,
)

VERSION = "draft-v2"
"""프롬프트 판 (생성_파이프라인 4절). 문구를 고치면 함께 올리세요 - **판을 올리지 않은 프롬프트
변경은 그 이전 실측을 전부 무효로 만듭니다.**

`draft-v2` 는 2026-08-29 에 `PRODUCT_STAGING` 이 붙으면서 올렸습니다. `draft-v1` 로 잰
숫자(지표 실측 보고서, 가드레일 거짓양성 갈래 보고서)와 섞어 읽지 마세요."""

DIALOGUE_LENGTH_HINT = 25
"""만화 대사 길이의 프롬프트 지침 (미결정_대장 N18, 2026-08-21 회의 확정).

⚠️ 이 값을 집행하는 검사 코드는 **없습니다.** 회의가 강제 검사를 만들지 않기로 정했고, 모델이
넘겨도 그대로 통과합니다. 값을 바꾸면 `VERSION` 도 함께 올리세요."""

GUARDRAIL_BLOCK = """[표현 가이드라인과 금지 사항]
- 아래 <근거>에 있는 내용만으로 씁니다. 그 밖의 지식, 상식, 추측을 쓰지 마세요.
- <근거>에 없는 효능, 수치, 성분, 수상 이력, 타사 비교를 만들어 내지 마세요.
- 카테고리와 타겟은 추론으로 채운 값이므로 근거가 아닙니다. 그것을 근거 삼아 효능을 쓰지 마세요.
- 최상급 표현("최고", "1위", "유일")은 근거에 그대로 적혀 있을 때만 씁니다."""
"""가드레일의 프롬프트 쪽 절반입니다 (생성_파이프라인 5.1절, INV-6).

⚠️ **이 블록을 지우는 것은 프롬프트를 줄이는 일이 아니라 가드레일을 절반 끄는 일입니다.**
없는 효능을 쓰면 표시광고법상 허위 과장 광고이고, on/off 델타 자체가 보고 지표입니다.

⚠️ 나머지 절반은 **출력 검증(`guardrail.check_claims`)이고 `draft._guarded_draft` 가
부릅니다** (2026-08-20, ADR-0019). 지시만으로는 위반 빈도를 낮출 뿐 빠져나온 것을 잡지
못하므로 둘 다 필요하고, 어느 한쪽만 두면 측정이 절반짜리가 됩니다.

⚠️ **`verify` 가 아닙니다.** 저쪽은 질의응답 경로의 어휘 겹침 판정이고, 광고 카피에 쓰면
지시문이 전부 위반으로 잡히면서 정작 타사 비교는 통과합니다 (2026-08-20 실측).
"""

EVIDENCE_HEADING = "<근거>"
"""주장의 근거는 `sellingPoint` + `note` 입니다 (생성_파이프라인 5.2절).

블록에 이름을 붙여 두는 이유는 금지 사항이 "무엇 밖을 쓰지 말라"고 가리킬 대상이 필요하기
때문입니다. 근거 표시가 없으면 위 블록은 아무것도 제한하지 못합니다.

⚠️ 블록 안에 **제품명도 함께** 들어갑니다. 근거를 넓히려는 것이 아니라 무엇을 광고하는지를
알려 주어야 하기 때문이고, 제품명은 사용자가 직접 친 글자라 효능을 실어 올 수 없습니다.
출력 검증도 같은 범위를 봅니다 (`draft._evidence`).
"""

ROLE_BEATS: dict[PanelRole, str] = {
    "hook": "후킹",
    "setup": "상황 제시",
    "problem": "문제와 고민",
    "solution": "제품 등장과 해결",
    "proof": "성능과 효과",
    "cta": "만족과 CTA (구매, 문의, 저장 등 다음 행동 유도)",
}
"""기획서 7.3 의 컷별 역할 템플릿. 순서는 `PANEL_ROLES` 가 정합니다 (INV-5).

⚠️ 한국어 문구를 여기 두는 이유는 계약의 `PanelRole` 이 영어 열거값이고 프롬프트는 한국어이기
때문입니다. 열거값에 한국어를 넣으면 계약이 바뀌고, 프롬프트에 영어를 넣으면 모델이 여섯 박자를
기획서와 다르게 해석합니다.
"""

PRODUCT_USED_AT: PanelRole = "solution"
"""인물이 제품을 쓰기 시작하는 칸의 역할 (기획서 7.3 의 4번 "제품 등장 및 해결").

⚠️ **"제품이 처음 화면에 나오는 칸" 이 아닙니다** (2026-08-29 에 뜻이 바뀌었습니다). 제품은
1번 칸부터 놓여 있고, 이 역할이 정하는 것은 인물이 그것을 쓰기 시작하는 자리 하나입니다 -
`PRODUCT_STAGING` 과 `render_prompt` 가 같은 값을 씁니다.

칸 번호가 아니라 역할로 적습니다. 번호는 역할에서 나오고(INV-5) 순서를 정하는 것은
`PANEL_ROLES` 이므로, 여기에 `4` 를 박으면 같은 사실이 두 곳에 생깁니다.
"""

PRODUCT_USED_AT_INDEX = PANEL_ROLES.index(PRODUCT_USED_AT) + 1
"""제품을 쓰기 시작하는 칸 번호. 프롬프트 문장이 사람에게 읽히는 번호로 말해야 해서 씁니다."""

PRODUCT_STAGING = (
    "1번 칸 장면에는 제품과 주배경이 반드시 들어갑니다. 1번 칸 그림이 나머지 다섯 칸의 "
    "기준이 되므로 여섯 칸은 같은 장소에서 이어집니다.\n"
    f"{PRODUCT_USED_AT_INDEX}번 칸 앞까지는 제품이 그 자리에 놓여 있기만 하고 인물이 들거나 "
    "쓰지 않습니다.\n"
    f"{PRODUCT_USED_AT_INDEX}번 칸은 인물이 제품을 어딘가에서 꺼내 오는 장면이 아니라, 이미 "
    "놓여 있는 제품을 알아보고 강조하는 장면입니다."
)
"""장면(`scene`)의 제품 배치 규칙 (2026-08-29 실물 회차).

⚠️ **그림 쪽 지시만으로는 부족합니다.** 렌더는 `scene` 을 그대로 받아 그리므로, 여기서
"가방에서 꺼낸다" 는 장면이 나오면 `render_prompt` 의 같은 규칙과 정면으로 부딪힙니다.
두 프롬프트가 한 쌍이며, 한쪽만 고치면 칸마다 다른 결과가 섞여 나옵니다.
"""


def build_generate(request: DraftGenerateRequest) -> str:
    """시안 하나를 쓰게 하는 지시문.

    ⚠️ `guardrail_applied=False` 면 금지 사항 블록이 **빠집니다.** 그것이 대조군의 정의이고
    (생성_파이프라인 5.3절), 켜 둔 채로 "가드레일 끔" 이라고 보고하면 환각 억제율이 0 으로
    나올 수밖에 없습니다. 근거 블록 자체는 남습니다 - 근거 없이 쓰라는 뜻이 아니라 금지
    지시 없이 쓰라는 뜻입니다.
    """
    sections = [
        "당신은 제품 정보만 보고 광고 소재의 텍스트 시안을 쓰는 작성자입니다.",
        *([GUARDRAIL_BLOCK] if request.guardrail_applied else []),
        _evidence(request.brief),
        _inferred(request.brief),
        f"[화풍]\n{request.brief.art_style}",
        _per_output_type(request),
        _output_shape(request.output_type == "comic"),
    ]
    return "\n\n".join(sections)


def build_patch(request: DraftPatchEngineRequest) -> str:
    """지정한 부분만 다시 쓰게 하는 지시문.

    ⚠️ **전체를 다시 쓰게 하지 않습니다** (생성_파이프라인 3절). 전체 재생성 후 diff 를
    취하는 방식은 지정하지 않은 컷의 대사까지 조용히 바꿉니다. 그래서 지금 시안 전체를
    맥락으로 보여 주되 **바꿀 자리만 출력하라고** 요구하고, 그 밖의 필드는 호출부가 원문에서
    그대로 복사합니다 - 모델이 돌려준 것을 믿지 않습니다.

    ⚠️ 패치 값은 **교체 문장이 아니라 사용자의 주문입니다.** 그대로 갖다 붙이는 것은 스텁이
    할 수 있는 유일하게 정직한 일이었을 뿐이고 (`draft._patch_stub`), 실물 분기에서 부분
    교체는 텍스트 호출 1회입니다 (생성_파이프라인 1절 3단계, 변동 비용이 생기는 유일한 자리).
    """
    sections = [
        "당신은 이미 쓰인 광고 시안의 지정된 부분만 다시 쓰는 작성자입니다.",
        *([GUARDRAIL_BLOCK] if request.guardrail_applied else []),
        _evidence(request.brief),
        _inferred(request.brief),
        f"[화풍]\n{request.brief.art_style}",
        _current_draft(request),
        _patch_instructions(request.patch, isinstance(request.draft, ComicDraft)),
        _patch_output_shape(request.patch, isinstance(request.draft, ComicDraft)),
    ]
    return "\n\n".join(sections)


def _evidence(brief: Brief) -> str:
    """제품 정보. 금지 사항이 가리키는 바로 그 블록입니다.

    ⚠️ 빈 문자열은 "비어 있음"이고 키 생략은 "해당 없음"입니다 (계약 3절). 빈 메모를 넣으면
    모델에게 빈 요청을 지시하게 되므로 넣지 않습니다.
    """
    lines = [
        EVIDENCE_HEADING,
        f"제품명: {brief.product_name}",
        f"소구점: {brief.selling_point}",
    ]
    if brief.note:
        lines.append(f"자유 메모: {brief.note}")
    lines.append("</근거>")
    return "\n".join(lines)


def _inferred(brief: Brief) -> str:
    """추론 결과. 근거 블록 **밖**에 둡니다 (생성_파이프라인 5.2절).

    ⚠️ 두 값을 근거와 같은 블록에 넣으면 위 금지 사항이 무력해집니다 - 추론으로 채운
    카테고리를 근거 삼아 효능을 쓰면 지어낸 것이 되는데, 프롬프트상으로는 근거를 지킨
    것처럼 보이기 때문입니다.
    """
    return f"[추론 결과]\n카테고리: {brief.category}\n타겟: {brief.target}"


def _per_output_type(request: DraftGenerateRequest) -> str:
    if request.output_type == "comic":
        return _comic_instructions(request.brief)
    return _single_ad_instructions(request.brief)


def _comic_instructions(brief: Brief) -> str:
    """6컷 고정, 역할도 고정 (기획서 7.3, INV-1, INV-5).

    ⚠️ **제품 배치 규칙이 함께 갑니다** (`PRODUCT_STAGING`, 2026-08-29). 칸 역할만 주면
    모델이 1번 칸을 제품 없는 후킹으로 쓰고, 그러면 그 칸을 레퍼런스로 보는 나머지 다섯
    칸에서 제품과 장소가 칸마다 달라집니다.

    ⚠️ 대사 길이 상한 25자는 **지침이지 규칙이 아닙니다** (N18, 2026-08-21 회의 확정).
    모델이 25자를 넘겨도 검사 코드가 거부하거나 재생성시키지 않습니다 - 회의가 강제 검사
    코드를 만들지 않는 쪽으로 정했기 때문입니다. 근거는 "운영 조건에서 15 ~ 25자가 전부
    무오탈자였다" 이고 "25자가 한계다" 가 아닙니다. **26자 이상은 재지 않았습니다.**

    세는 규칙을 프롬프트에 적지 않은 것은 집행하는 코드가 없기 때문입니다. 나중에 검사를
    붙이게 되면 그때 `len()`(공백과 문장부호 포함)으로 맞춥니다.
    """
    beats = "\n".join(
        f"{index}번 칸: {ROLE_BEATS[role]}" for index, role in enumerate(PANEL_ROLES, start=1)
    )
    lines = [
        "[유형별 지시]",
        "6칸 만화의 장면과 대사를 씁니다. 칸 수와 칸별 역할은 고정이며 바꿀 수 없습니다.",
        beats,
        "같은 인물이 여섯 칸 모두에 같은 얼굴과 복장으로 등장합니다.",
        PRODUCT_STAGING,
    ]
    if brief.character is not None:
        lines.append(f"인물: 외모는 {brief.character.appearance}, 복장은 {brief.character.outfit}.")
    lines.append(
        f"말풍선 대사는 한 문장으로 짧게 씁니다. 공백과 문장부호를 포함해 "
        f"{DIALOGUE_LENGTH_HINT}자를 넘기지 마세요. 장면 설명을 대사에 넣지 마세요."
    )
    return "\n".join(lines)


def _single_ad_instructions(brief: Brief) -> str:
    """단일 광고형은 한 화면입니다.

    ⚠️ 카피와 비주얼 구성안을 갈라 두는 것이 요점입니다. 합치면 렌더 단계에서 모델이 기획
    문장을 이미지 안에 써 넣습니다 (`render_prompt._single_ad` 의 같은 주의).
    """
    lines = [
        "[유형별 지시]",
        "한 화면짜리 광고 1장의 카피와 비주얼 구성안을 씁니다.",
        "광고 기획안은 왜 이 구성인지를 설명하는 한 문단입니다.",
        "카피는 이미지 안에 그려질 문구입니다. 한 문장으로 짧게 씁니다.",
        "비주얼 구성안은 무엇을 어떻게 배치할지입니다. 이미지 안에 쓸 글자를 여기 넣지 마세요.",
    ]
    if brief.aspect_ratio:
        lines.append(f"화면 비율: {brief.aspect_ratio}.")
    return "\n".join(lines)


COMIC_SHAPE = (
    '{"adPlan": "<광고 기획안 한 문단>", "panels": ['
    '{"scene": "<장면>", "dialogue": "<대사>"}, ... 정확히 6개]}'
)
SINGLE_AD_SHAPE = (
    '{"adPlan": "<광고 기획안 한 문단>", "copy": "<카피>", "visualPlan": "<비주얼 구성안>"}'
)
REFUSAL_SHAPE = '{"refusal": "no_evidence"}'
"""거절도 정상 응답입니다 (계약 `DraftGenerateResponse`). 200 이며 `draft` 가 빠집니다.

⚠️ 거절 갈래를 프롬프트에서 빼면 모델은 근거가 없어도 무언가를 씁니다. "지어내지 마세요" 만
있고 "대신 이렇게 답하세요" 가 없으면 남는 선택지가 지어내는 것뿐이기 때문입니다.
"""


def retry_block(violations: tuple[tuple[str, str], ...]) -> str:
    """1회차 위반 뒤 다시 쓰게 할 때 프롬프트 끝에 붙입니다 (생성_파이프라인 5.1.1절).

    ⚠️ **걸린 표현을 지목합니다.** "규칙을 어겼다" 만 알려 주면 모델이 같은 문장을 다시 쓰고,
    그러면 재생성 1회가 요금만 쓰고 끝납니다.

    ⚠️ 재생성은 **한 번뿐입니다.** 열어 두면 거절이 반복될 때 비용이 무한히 늡니다. 그리고
    서버가 위반 문구를 임의로 다듬어 내보내지 않습니다 - 다듬은 결과가 근거 안에 있는지를
    다시 검사하는 사람이 아무도 없기 때문입니다 (ADR-0005).
    """
    listed = "\n".join(
        f"- {found!r} ({_VIOLATION_LABELS.get(kind, kind)})" for kind, found in violations
    )
    return (
        "[다시 씁니다]\n"
        "방금 쓴 문구에 근거 밖 표현이 있었습니다. 아래 표현을 빼고 같은 형식으로 다시 씁니다.\n"
        f"{listed}\n"
        "빼는 대신 다른 수치나 비교로 바꾸지 마세요. 근거에 있는 말로만 쓰거나, 그 부분을 덜어 냅니다."
    )


_VIOLATION_LABELS: dict[str, str] = {
    "number": "근거에 없는 수치",
    "comparison": "타사 비교",
    "superlative": "최상급 표현",
    "award": "수상이나 인증 주장",
}
"""`guardrail.ClaimKind` 를 모델에게 보여 줄 한국어로. 열거값을 그대로 쓰면 영어 식별자가
프롬프트에 섞입니다."""


def _output_shape(is_comic: bool) -> str:
    """출력 규격. JSON 하나만 받습니다.

    ⚠️ `index` 와 `role` 을 **요구하지 않습니다.** 칸 번호는 배열 순서이고 역할은 번호가
    정합니다 (INV-5). 모델에게 물으면 모델이 정한 값이 되고, 그 순간 여섯 박자가 기획 근거가
    아니라 회차마다 흔들리는 값이 됩니다.
    """
    lines = [
        "[출력 규격]",
        "JSON 하나만 출력합니다. 설명도 머리말도 코드 블록 표시도 붙이지 마세요.",
        COMIC_SHAPE if is_comic else SINGLE_AD_SHAPE,
    ]
    if is_comic:
        lines.append("배열 순서가 곧 칸 번호입니다. index 와 role 은 쓰지 마세요.")
    lines.append(f"근거만으로는 쓸 수 없으면 지어내지 말고 이것만 출력합니다: {REFUSAL_SHAPE}")
    return "\n".join(lines)


def _current_draft(request: DraftPatchEngineRequest) -> str:
    """지금 시안 전체. 맥락으로만 씁니다.

    바꾸지 않을 부분까지 보여 주는 이유는 지정된 자리만 고쳐도 나머지와 말이 맞아야 하기
    때문입니다. 그러나 **되돌려 받지는 않습니다** - 출력 규격이 바꿀 자리만 요구합니다.
    """
    draft = request.draft
    lines = ["[지금 시안]", f"광고 기획안: {draft.ad_plan}"]
    if isinstance(draft, ComicDraft):
        lines += [
            f"{panel.index}번 칸 ({ROLE_BEATS[panel.role]}): 장면 {panel.scene} / "
            f"대사 {panel.dialogue}"
            for panel in draft.panels
        ]
    else:
        lines += [f"카피: {draft.ad_copy}", f"비주얼 구성안: {draft.visual_plan}"]
    return "\n".join(lines)


PANEL_FIELD_LABELS: dict[str, str] = {"scene": "장면", "dialogue": "대사"}
"""`PanelPatch` 의 필드 이름을 프롬프트에 쓸 한국어로. 계약은 영어, 프롬프트는 한국어입니다."""


def _named_panel_cells(patch: DraftPatch) -> list[tuple[str, str, str]]:
    """패치가 이름 붙인 (칸 번호, 필드 이름, 사용자가 적은 주문) 을 읽는 순서대로.

    ⚠️ `model_fields_set` 을 읽습니다. 이 계열에서 `""` 는 "비워라" 라는 정상 지시이고
    `None` 은 키가 없었다는 뜻뿐이라, 값으로 판단하면 정반대의 두 요청이 하나로 뭉개집니다
    (`models/patch.py`).
    """
    if patch.panels is None:
        return []
    return [
        (index, name, getattr(cell, name))
        for index, cell in sorted(patch.panels.root.items())
        for name in PANEL_FIELD_LABELS
        if name in cell.model_fields_set
    ]


def _patch_instructions(patch: DraftPatch, is_comic: bool) -> str:
    """무엇을 왜 바꾸는지. 값은 사용자의 주문입니다."""
    lines = ["[바꿀 부분]", "아래에 적힌 자리만 다시 씁니다. 그 밖의 부분은 건드리지 마세요."]
    if is_comic:
        lines += [
            f"{index}번 칸 {PANEL_FIELD_LABELS[name]}: {order!r} 라는 주문에 맞게"
            for index, name, order in _named_panel_cells(patch)
        ]
    if "ad_copy" in patch.model_fields_set:
        lines.append(f"카피: {patch.ad_copy!r} 라는 주문에 맞게")
    if "visual_plan" in patch.model_fields_set:
        lines.append(f"비주얼 구성안: {patch.visual_plan!r} 라는 주문에 맞게")
    lines.append("주문이 빈 문자열이면 그 자리를 비우라는 뜻입니다.")
    return "\n".join(lines)


def _patch_output_shape(patch: DraftPatch, is_comic: bool) -> str:
    """바꾼 자리만 담은 JSON. 나머지 키는 아예 요구하지 않습니다.

    ⚠️ 전체 시안을 돌려받는 형식으로 두면 모델이 손대지 말라고 한 곳까지 다시 써서 보내고,
    호출부는 그것을 걸러 내야 합니다. 애초에 요구하지 않는 편이 안전합니다 - 그래도 호출부는
    원문에서 복사하지 응답을 믿지 않습니다 (`draft._patch_with_model`).
    """
    if is_comic:
        named: dict[str, list[str]] = {}
        for index, name, _ in _named_panel_cells(patch):
            named.setdefault(index, []).append(f'"{name}": "<새 {PANEL_FIELD_LABELS[name]}>"')
        cells = ", ".join(f'"{index}": {{{", ".join(fields)}}}' for index, fields in named.items())
        shape = f'{{"panels": {{{cells}}}}}'
    else:
        keys = []
        if "ad_copy" in patch.model_fields_set:
            keys.append('"copy": "<새 카피>"')
        if "visual_plan" in patch.model_fields_set:
            keys.append('"visualPlan": "<새 비주얼 구성안>"')
        shape = f"{{{', '.join(keys)}}}"
    return (
        "[출력 규격]\n"
        "JSON 하나만 출력합니다. 설명도 머리말도 코드 블록 표시도 붙이지 마세요.\n"
        f"{shape}\n"
        f"근거만으로는 쓸 수 없으면 지어내지 말고 이것만 출력합니다: {REFUSAL_SHAPE}"
    )

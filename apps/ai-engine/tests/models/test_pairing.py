"""The rules no single schema can express: output type versus brief, and versus draft.

The contract carries these as prose ("적용되지 않는 유형에서는 필드 자체가 없습니다") because
`Brief` has no `outputType` and neither draft shape has a discriminator. Nothing in the
conformance tests would notice if they stopped being enforced — field names would still
match — so they get their own tests.
"""

import pytest
from pydantic import ValidationError

from ai_engine.models import (
    PANEL_ROLES,
    Brief,
    ComicDraft,
    DraftGenerateRequest,
    ImageRenderRequest,
    ImageSpec,
    Panel,
    SingleAdDraft,
)

BRIEF_FIELDS = {
    "productImageUrl": "https://example.test/a.webp",
    "productName": "핸드크림",
    "sellingPoint": "하루 종일 촉촉합니다",
    "note": "",
    "category": "뷰티",
    "target": "30대 직장인",
    "artStyle": "watercolor",
}


def single_ad_brief(**overrides: object) -> Brief:
    return Brief.model_validate({**BRIEF_FIELDS, **overrides})


def comic_brief(**overrides: object) -> Brief:
    return Brief.model_validate(
        {**BRIEF_FIELDS, "character": {"appearance": "단발", "outfit": "니트"}, **overrides}
    )


SINGLE_AD_DRAFT = SingleAdDraft(ad_plan="기획안", ad_copy="카피", visual_plan="비주얼")
COMIC_DRAFT = ComicDraft(
    ad_plan="기획안",
    panels=[
        Panel(index=index, role=role, scene="장면", dialogue="대사")
        for index, role in enumerate(
            ["hook", "setup", "problem", "solution", "proof", "cta"], start=1
        )
    ],
)


# ---- 유형에 맞지 않는 브리프 필드 ------------------------------------------------


def test_comic_brief_may_not_carry_aspect_ratio() -> None:
    # Built outside the block on purpose: with the helper inside it, a failure there would
    # pass this test for the wrong reason and the pairing check could quietly stop running.
    brief = comic_brief(aspectRatio="1:1")
    with pytest.raises(ValidationError, match="aspectRatio"):
        DraftGenerateRequest(output_type="comic", brief=brief)


def test_single_ad_brief_may_not_carry_character() -> None:
    brief = single_ad_brief(character={"appearance": "단발", "outfit": "니트"})
    with pytest.raises(ValidationError, match="character"):
        DraftGenerateRequest(output_type="single_ad", brief=brief)


def test_matching_pairs_are_accepted() -> None:
    assert DraftGenerateRequest(output_type="comic", brief=comic_brief()).brief.character
    assert single_ad_brief(aspectRatio="1:1").aspect_ratio == "1:1"


def test_the_field_is_absent_rather_than_empty_when_it_does_not_apply() -> None:
    """Absence, not `""` — an empty string would mean "applies, but blank"."""
    dumped = single_ad_brief().model_dump(by_alias=True)
    assert "character" not in dumped
    assert "aspectRatio" not in dumped


# ---- 유형과 시안 실체의 불일치 ---------------------------------------------------


def test_draft_union_resolves_by_shape() -> None:
    """No discriminator field exists; `extra="forbid"` is what makes the union decidable."""
    request = ImageRenderRequest.model_validate(
        {
            "outputType": "single_ad",
            "brief": BRIEF_FIELDS,
            "draft": {"adPlan": "기획안", "copy": "카피", "visualPlan": "비주얼"},
            "spec": {"width": 1088, "height": 1088},
            "quality": "low",
        }
    )
    assert isinstance(request.draft, SingleAdDraft)


def test_a_draft_mixing_both_shapes_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ImageRenderRequest.model_validate(
            {
                "outputType": "single_ad",
                "brief": BRIEF_FIELDS,
                "draft": {"adPlan": "기획안", "copy": "카피", "visualPlan": "비주얼", "panels": []},
                "spec": {"width": 1088, "height": 1088},
                "quality": "low",
            }
        )


def test_comic_output_type_rejects_a_single_ad_draft() -> None:
    """⚠️ Without the pairing check this validates cleanly — the union accepts either."""
    brief, spec = comic_brief(), ImageSpec(width=3456, height=2304)
    with pytest.raises(ValidationError, match="expected ComicDraft"):
        ImageRenderRequest(
            output_type="comic",
            brief=brief,
            draft=SINGLE_AD_DRAFT,
            spec=spec,
            quality="medium",
        )


def test_single_ad_output_type_rejects_a_comic_draft() -> None:
    brief, spec = single_ad_brief(), ImageSpec(width=1088, height=1088)
    with pytest.raises(ValidationError, match="expected SingleAdDraft"):
        ImageRenderRequest(
            output_type="single_ad",
            brief=brief,
            draft=COMIC_DRAFT,
            spec=spec,
            quality="low",
        )


# ---- 컷과 규격 -----------------------------------------------------------------


def test_a_comic_draft_needs_exactly_six_panels() -> None:
    """0 and 7 are both invalid (INV-1) — six beats are the planning rationale itself."""
    with pytest.raises(ValidationError):
        ComicDraft(ad_plan="기획안", panels=COMIC_DRAFT.panels[:5])


def test_the_panel_roles_are_in_the_order_the_planning_document_gives() -> None:
    """⚠️ `PANEL_ROLES[index - 1]` 이 그 칸의 역할이라는 규약이 여기 걸려 있습니다 (INV-5).

    순서가 `Literal` 선언 순서에서 나오므로, 누군가 열거값을 알파벳순으로 정리하는 것만으로도
    4번 칸이 "제품 등장과 해결" 이 아니게 됩니다 - 스키마는 그대로 통과하고 생성된 만화의
    이야기 구조만 조용히 무너집니다. 기준은 기획서 7.3 의 표입니다.
    """
    assert PANEL_ROLES == ("hook", "setup", "problem", "solution", "proof", "cta")
    assert len(PANEL_ROLES) == 6


def test_image_spec_rejects_sizes_the_model_cannot_produce() -> None:
    """Both sides must be multiples of 16 and within the long-edge limit."""
    with pytest.raises(ValidationError):
        ImageSpec(width=1000, height=1088)
    with pytest.raises(ValidationError):
        ImageSpec(width=4096, height=1088)

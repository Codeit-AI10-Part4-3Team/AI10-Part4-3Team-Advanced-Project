"""The rules no single schema can express: output type versus brief, versus draft, versus
patch.

The contract carries these as prose ("적용되지 않는 유형에서는 필드 자체가 없습니다") because
`Brief` has no `outputType`, neither draft shape has a discriminator, and `DraftPatch` holds
every type's fields at once. Nothing in the conformance tests would notice if they stopped
being enforced — field names would still match — so they get their own tests.
"""

import pytest
from pydantic import ValidationError

from backend_core.models import (
    Brief,
    ComicDraft,
    DraftGenerateRequest,
    DraftPatch,
    ImageRenderRequest,
    ImageSpec,
    OutputType,
    Panel,
    SingleAdDraft,
    check_patch_matches_output_type,
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


# ---- 유형에 맞지 않는 패치 필드 --------------------------------------------------


@pytest.mark.parametrize(
    ("output_type", "patch_fields", "expected"),
    [
        ("single_ad", {"panels": {"4": {"dialogue": "새 대사"}}}, "panels"),
        ("single_ad", {"panels": {"4": {"dialogue": "새 대사"}}, "copy": "새 카피"}, "panels"),
        ("comic", {"copy": "새 카피"}, "copy"),
        ("comic", {"visualPlan": "새 비주얼"}, "visualPlan"),
    ],
    ids=["single_ad + panels", "single_ad + panels and copy", "comic + copy", "comic + visualPlan"],
)
def test_a_patch_may_not_name_the_other_output_types_fields(
    output_type: OutputType, patch_fields: dict[str, object], expected: str
) -> None:
    """⚠️ The one of the three with no symptom when it is missing.

    A mismatched brief or draft changes the shape of what comes back; a mismatched patch
    does not. The engine's stub simply skipped the field that did not apply and returned
    200 with an unchanged draft, so "the patch was ignored" and "the patch was applied"
    looked identical on the wire (2026-08-18 실측).

    The `panels and copy` case is the one that made it invisible in practice: the copy did
    change, so the response was not even suspicious.
    """
    patch = DraftPatch.model_validate(patch_fields)
    with pytest.raises(ValueError, match=expected):
        check_patch_matches_output_type(output_type, patch)


@pytest.mark.parametrize(
    ("output_type", "patch_fields"),
    [
        ("single_ad", {"copy": "새 카피", "visualPlan": "새 비주얼"}),
        ("comic", {"panels": {"4": {"dialogue": "새 대사"}}}),
    ],
    ids=["single_ad", "comic"],
)
def test_a_patch_naming_only_its_own_types_fields_is_accepted(
    output_type: OutputType, patch_fields: dict[str, object]
) -> None:
    """The other half — without this the check could reject everything and still pass."""
    patch = DraftPatch.model_validate(patch_fields)
    check_patch_matches_output_type(output_type, patch)


def test_an_empty_string_in_a_patch_is_an_instruction_not_an_absence() -> None:
    """⚠️ The check reads `model_fields_set`, not the values. `copy: ""` means "empty it" in
    this family, so a comic patch naming it is still a mismatch — testing for truthiness
    would let it through."""
    patch = DraftPatch.model_validate({"copy": ""})
    with pytest.raises(ValueError, match="copy"):
        check_patch_matches_output_type("comic", patch)


# ---- 컷과 규격 -----------------------------------------------------------------


def test_a_comic_draft_needs_exactly_six_panels() -> None:
    """0 and 7 are both invalid (INV-1) — six beats are the planning rationale itself."""
    with pytest.raises(ValidationError):
        ComicDraft(ad_plan="기획안", panels=COMIC_DRAFT.panels[:5])


def test_image_spec_rejects_sizes_the_model_cannot_produce() -> None:
    """Both sides must be multiples of 16 and within the long-edge limit."""
    with pytest.raises(ValidationError):
        ImageSpec(width=1000, height=1088)
    with pytest.raises(ValidationError):
        ImageSpec(width=4096, height=1088)

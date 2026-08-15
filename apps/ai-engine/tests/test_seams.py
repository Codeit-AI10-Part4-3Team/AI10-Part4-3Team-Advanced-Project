"""The generation seams: brief:fill, draft:generate, draft:patch, image:render.

What these tests are for is not "the stub returns something". It is that the **seam** holds:
the same function branches on one setting, the stub side is unmistakably a stub, and the
unwritten side fails loudly instead of quietly producing something plausible
(구현_범위 1.1절).
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ai_engine import brief_fill, draft, render, service
from ai_engine.config import Settings
from ai_engine.models import (
    Brief,
    ComicDraft,
    DraftGenerateRequest,
    DraftPatch,
    DraftPatchEngineRequest,
    ImageRenderRequest,
    ImageSpec,
    OutputType,
    Panel,
    SingleAdDraft,
)
from ai_engine.service_schemas import BriefFillRequest

BRIEF_FIELDS = {
    "productImageUrl": "https://example.test/a.webp",
    "productName": "핸드크림",
    "sellingPoint": "하루 종일 촉촉합니다",
    "note": "",
    "category": "뷰티",
    "target": "30대 직장인",
    "artStyle": "watercolor",
}


@pytest.fixture
def stub_settings() -> Settings:
    return Settings(generation_mode="stub")


@pytest.fixture
def model_settings() -> Settings:
    """The mode whose branches are not written yet."""
    return Settings(generation_mode="model")


def brief() -> Brief:
    return Brief.model_validate(BRIEF_FIELDS)


def render_request(width: int = 1088, height: int = 1088) -> ImageRenderRequest:
    return ImageRenderRequest(
        output_type="single_ad",
        brief=brief(),
        draft=draft.SingleAdDraft(ad_plan="기획안", ad_copy="카피", visual_plan="비주얼"),
        spec=ImageSpec(width=width, height=height),
    )


def draft_request(
    output_type: OutputType = "single_ad", brief_override: Brief | None = None
) -> DraftGenerateRequest:
    return DraftGenerateRequest(
        output_type=output_type,
        brief=brief_override if brief_override is not None else brief(),
    )


def single_ad_draft() -> SingleAdDraft:
    return SingleAdDraft(ad_plan="기획안", ad_copy="원래 카피", visual_plan="원래 비주얼")


def patch_request(**patch_fields: object) -> DraftPatchEngineRequest:
    return DraftPatchEngineRequest(
        output_type="single_ad",
        brief=brief(),
        draft=single_ad_draft(),
        patch=DraftPatch.model_validate(patch_fields),
    )


def fill_request() -> BriefFillRequest:
    return BriefFillRequest.model_construct(
        product_image=None, product_name="핸드크림", selling_point="하루 종일 촉촉합니다"
    )


# ---- 분기가 설정 하나로 갈리는가 ------------------------------------------------


def test_model_branch_fails_loudly_on_every_seam(model_settings: Settings) -> None:
    """⚠️ The point of the whole design. An unwritten branch must not degrade politely.

    A stub returned from the model branch would be indistinguishable from a real result in
    every log, metric and screenshot.
    """
    # Requests are built outside the blocks: a failure while building one would pass these
    # tests for the wrong reason, and then the branch could stop raising unnoticed.
    fill, generate, image = fill_request(), draft_request(), render_request()
    patch = patch_request(copy="새 카피")

    with pytest.raises(NotImplementedError, match="ADGEN_GENERATION_MODE"):
        brief_fill.fill_brief(fill, model_settings)
    with pytest.raises(NotImplementedError, match="ADGEN_GENERATION_MODE"):
        draft.generate_draft(generate, model_settings)
    with pytest.raises(NotImplementedError, match="ADGEN_GENERATION_MODE"):
        draft.patch_draft(patch, model_settings)
    with pytest.raises(NotImplementedError, match="ADGEN_GENERATION_MODE"):
        render.render_image(image, model_settings)


def test_the_mode_is_readable_without_opening_the_source() -> None:
    assert brief_fill.describe_mode("stub") != brief_fill.describe_mode("model")


# ---- S3 브리프 채우기 -------------------------------------------------------------


def test_brief_fill_stub_marks_its_output(stub_settings: Settings) -> None:
    """A convincing stub is a stub that ends up in a report as a measurement."""
    response = brief_fill.fill_brief(fill_request(), stub_settings)
    assert stub_settings.stub_marker in response.category
    assert stub_settings.stub_marker in response.target


def test_brief_fill_stub_always_decides(stub_settings: Settings) -> None:
    """`needsInput` stays absent so the skeleton exercises the straight path."""
    response = brief_fill.fill_brief(fill_request(), stub_settings)
    assert "needsInput" not in response.model_dump(by_alias=True)


# ---- S4 시안 생성 -----------------------------------------------------------------


def test_draft_stub_grounds_the_copy_in_the_selling_point(stub_settings: Settings) -> None:
    """⚠️ Even a stub may not put a claim on the wire that the input did not carry.

    `sellingPoint` (+ `note`) is the guardrail's evidence; `category` and `target` are
    inferred and are not.
    """
    response = draft.generate_draft(
        DraftGenerateRequest(output_type="single_ad", brief=brief()), stub_settings
    )
    assert response.draft is not None
    assert "하루 종일 촉촉합니다" in response.draft.ad_copy
    assert "30대 직장인" not in response.draft.ad_copy


def test_draft_stub_echoes_guardrail_applied(stub_settings: Settings) -> None:
    """The control-run flag must survive, or the suppression rate cannot be computed."""
    request = DraftGenerateRequest(output_type="single_ad", brief=brief(), guardrail_applied=False)
    assert draft.generate_draft(request, stub_settings).guardrail_applied is False


def test_comic_branch_exists_but_is_not_faked(stub_settings: Settings) -> None:
    """The branch is structure (기획서 5.3); filling it with six fake panels would make the
    comic path look finished."""
    comic = Brief.model_validate(
        {**BRIEF_FIELDS, "character": {"appearance": "단발", "outfit": "니트"}}
    )
    request = draft_request("comic", comic)
    with pytest.raises(NotImplementedError, match="comic"):
        draft.generate_draft(request, stub_settings)


# ---- S6 렌더 ----------------------------------------------------------------------


def test_render_stub_returns_lossless_webp_at_the_requested_size(
    stub_settings: Settings,
) -> None:
    """Size and format are contract, not placeholder conveniences.

    The job reports `width`/`height` from what comes back, and 검증 1순위 scores glyphs, so
    a lossy or differently sized placeholder would misreport both.
    """
    payload = render.render_image(render_request(width=1088, height=1088), stub_settings)
    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WEBP"
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (1088, 1088)
        assert image.format == "WEBP"


def test_render_stub_honours_a_comic_sized_request(stub_settings: Settings) -> None:
    request = render_request(width=3456, height=2304)
    with Image.open(io.BytesIO(render.render_image(request, stub_settings))) as image:
        assert image.size == (3456, 2304)


# ---- 라우트 ------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(service.app)


def test_draft_generate_route_returns_a_draft(client: TestClient) -> None:
    response = client.post(
        "/v1/draft:generate", json={"outputType": "single_ad", "brief": BRIEF_FIELDS}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body["draft"]) == {"adPlan", "copy", "visualPlan"}
    assert body["guardrailApplied"] is True
    assert "refusalReason" not in body


def test_image_render_route_returns_webp_bytes(client: TestClient) -> None:
    response = client.post(
        "/v1/image:render",
        json={
            "outputType": "single_ad",
            "brief": BRIEF_FIELDS,
            "draft": {"adPlan": "기획안", "copy": "카피", "visualPlan": "비주얼"},
            "spec": {"width": 1088, "height": 1088},
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.content[:4] == b"RIFF"


def test_image_render_is_documented_as_webp_not_json(client: TestClient) -> None:
    """⚠️ Regression guard. FastAPI defaults to `application/json`, and the published
    contract would then claim JSON for a body that is image bytes."""
    spec = client.get("/openapi.json").json()
    content = spec["paths"]["/v1/image:render"]["post"]["responses"]["200"]["content"]
    assert list(content) == ["image/webp"]


def test_brief_fill_is_documented_as_multipart(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    content = spec["paths"]["/v1/brief:fill"]["post"]["requestBody"]["content"]
    assert list(content) == ["multipart/form-data"]


def test_brief_fill_route_accepts_an_upload(client: TestClient) -> None:
    response = client.post(
        "/v1/brief:fill",
        data={"productName": "핸드크림", "sellingPoint": "하루 종일 촉촉합니다"},
        files={"productImage": ("a.webp", b"RIFFfakeWEBP", "image/webp")},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"category", "target"}


def test_every_generation_path_documents_503(client: TestClient) -> None:
    """계약이 생성 경로 전부에 503 을 적고 있으므로 발행 스펙에도 있어야 합니다.

    ⚠️ FastAPI 는 `raise HTTPException(503)` 을 스펙에 자동으로 넣지 않습니다. 빠지면 계약에는
    있고 발행 스펙에는 없는 상태가 되고, 프론트엔드가 계약을 보고 짠 분기가 근거를 잃습니다.
    """
    spec = client.get("/openapi.json").json()
    for path in ("/v1/brief:fill", "/v1/draft:generate", "/v1/draft:patch", "/v1/image:render"):
        assert "503" in spec["paths"][path]["post"]["responses"], path


def test_unimplemented_model_branch_surfaces_as_503_not_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """호출자에게는 재시도 가능한 상태여야 합니다. 500 은 계약에 없는 답입니다.

    ⚠️ 스텁이 아니라 **실물 분기가 비어 있을 때**의 동작입니다. 이것이 500 으로 새면 화면이
    분기할 근거가 없고, 로그에서도 우리 결함과 상류 장애가 구분되지 않습니다.
    """
    monkeypatch.setattr(service, "settings", lambda: Settings(generation_mode="model"))
    response = client.post(
        "/v1/draft:generate", json={"outputType": "single_ad", "brief": BRIEF_FIELDS}
    )
    assert response.status_code == 503


# ---- draft:patch (2026-08-15) ---------------------------------------------------------


def test_patch_changes_only_what_it_names(stub_settings: Settings) -> None:
    """⚠️ The property that separates 부분 교체 from regeneration.

    A caller that asked to change the copy has a visual plan the user already approved.
    Rewriting it too would discard a decision, and would do so invisibly — the response
    shape is identical either way.
    """
    request = patch_request(copy="새 카피")

    response = draft.patch_draft(request, stub_settings)

    assert response.draft is not None
    assert "새 카피" in response.draft.ad_copy
    assert response.draft.visual_plan == "원래 비주얼"
    assert response.draft.ad_plan == "기획안"


def test_patch_can_empty_a_field_without_it_meaning_leave_it_alone(
    stub_settings: Settings,
) -> None:
    """⚠️ `""` and an absent key are opposite instructions in this family. A patch built
    with `exclude_none` would collapse them and "clear this" would become "keep this"."""
    request = patch_request(visualPlan="")

    response = draft.patch_draft(request, stub_settings)

    assert response.draft is not None
    assert response.draft.ad_copy == "원래 카피"
    assert response.draft.visual_plan.endswith("] ")


def test_an_empty_patch_is_refused(stub_settings: Settings) -> None:
    """`minProperties: 1`. A patch that names nothing applies no change and still costs the
    caller a revision, which invalidates every other open screen's optimistic lock."""
    with pytest.raises(ValueError, match="at least one field"):
        patch_request()


def test_the_patch_cannot_name_the_read_only_fields() -> None:
    """`adPlan` is INV-8 and `role` is INV-5; neither exists on the schema, so both are
    rejected as unknown fields rather than by a rule someone has to remember."""
    for field in ("adPlan", "role"):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            patch_request(**{field: "무엇이든"})


def test_the_comic_branch_of_the_patch_stub_raises(stub_settings: Settings) -> None:
    """Comic-blind like `_generate_stub`: patching six panels here would make the comic path
    look finished (구현_범위 1절)."""
    request = DraftPatchEngineRequest(
        output_type="comic",
        brief=Brief.model_validate(
            {**BRIEF_FIELDS, "character": {"appearance": "단발", "outfit": "니트"}}
        ),
        draft=ComicDraft(
            ad_plan="기획안",
            panels=[
                Panel(index=index, role=role, scene="장면", dialogue="대사")
                for index, role in enumerate(
                    ["hook", "setup", "problem", "solution", "proof", "cta"], start=1
                )
            ],
        ),
        patch=DraftPatch.model_validate({"panels": {"4": {"dialogue": "새 대사"}}}),
    )

    with pytest.raises(NotImplementedError, match="구현_범위"):
        draft.patch_draft(request, stub_settings)


def test_draft_patch_route_returns_the_patched_draft(client: TestClient) -> None:
    """⚠️ The route this file exists to add. Until 2026-08-15 it did not exist while the
    contract and the caller both did, so S5 answered 404 against a real engine — which the
    caller reports as `503 UPSTREAM_UNAVAILABLE`, pointing at a healthy service."""
    response = client.post(
        "/v1/draft:patch",
        json={
            "outputType": "single_ad",
            "brief": BRIEF_FIELDS,
            "draft": {"adPlan": "기획안", "copy": "원래 카피", "visualPlan": "원래 비주얼"},
            "patch": {"copy": "새 카피"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "새 카피" in body["draft"]["copy"]
    assert body["draft"]["visualPlan"] == "원래 비주얼"
    assert body["guardrailApplied"] is True


def test_draft_patch_route_rejects_an_empty_patch(client: TestClient) -> None:
    response = client.post(
        "/v1/draft:patch",
        json={
            "outputType": "single_ad",
            "brief": BRIEF_FIELDS,
            "draft": {"adPlan": "기획안", "copy": "원래 카피", "visualPlan": "원래 비주얼"},
            "patch": {},
        },
    )

    assert response.status_code == 422

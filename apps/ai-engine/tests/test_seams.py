"""The three walking-skeleton seams: brief:fill, draft:generate, image:render.

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
from ai_engine.models import Brief, DraftGenerateRequest, ImageRenderRequest, ImageSpec
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
    with pytest.raises(NotImplementedError, match="ADGEN_GENERATION_MODE"):
        brief_fill.fill_brief(fill_request(), model_settings)
    with pytest.raises(NotImplementedError, match="ADGEN_GENERATION_MODE"):
        draft.generate_draft(
            DraftGenerateRequest(output_type="single_ad", brief=brief()), model_settings
        )
    with pytest.raises(NotImplementedError, match="ADGEN_GENERATION_MODE"):
        render.render_image(render_request(), model_settings)


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
    with pytest.raises(NotImplementedError, match="comic"):
        draft.generate_draft(DraftGenerateRequest(output_type="comic", brief=comic), stub_settings)


# ---- S6 렌더 ----------------------------------------------------------------------


def test_render_stub_returns_lossless_webp_at_the_requested_size(
    stub_settings: Settings,
) -> None:
    """Size and format are contract, not placeholder conveniences.

    The job reports `width`/`height` from what comes back, and 검증 1순위 scores glyphs, so
    a lossy or differently sized placeholder would misreport both.
    """
    payload = render.render_image(render_request(width=1088, height=1088), stub_settings)
    assert payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
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

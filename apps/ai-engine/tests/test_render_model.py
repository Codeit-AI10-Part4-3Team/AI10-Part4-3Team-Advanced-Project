"""`image:render` 의 실물 분기 — 프롬프트 조립과 실패 처리.

⚠️ **외부 API 를 부르지 않습니다.** 호출 1회가 요금이고 CI 가 비결정적이 됩니다 (AGENTS.md).
여기서 검증하는 것은 "그림이 예쁜가"가 아니라 **우리가 무엇을 보내고 실패를 어떻게 다루는가**
이며, 둘 다 호출 없이 확인할 수 있는 성질입니다. 그림의 품질은 검증 1순위의 몫입니다.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from PIL import Image

from ai_engine import render, render_prompt
from ai_engine.config import Settings
from ai_engine.models import (
    Brief,
    ComicDraft,
    ImageRenderRequest,
    ImageSpec,
    Panel,
    SingleAdDraft,
)

BRIEF_FIELDS = {
    "productImageUrl": "/v1/sessions/abc/image",
    "productName": "순한 대나무 물티슈",
    "sellingPoint": "무향 무알코올, 두꺼운 원단",
    "note": "",
    "category": "생활용품",
    "target": "30대 주부",
    "artStyle": "korean_webtoon",
}


def single_ad_request(**brief_overrides: object) -> ImageRenderRequest:
    return ImageRenderRequest(
        output_type="single_ad",
        brief=Brief.model_validate({**BRIEF_FIELDS, **brief_overrides}),
        draft=SingleAdDraft(
            ad_plan="기획안 문장",
            ad_copy="한 장이면 충분해",
            visual_plan="제품 단독 컷, 밝은 주방 배경",
        ),
        spec=ImageSpec(width=1088, height=1088),
    )


def comic_request() -> ImageRenderRequest:
    roles = ["hook", "setup", "problem", "solution", "proof", "cta"]
    return ImageRenderRequest(
        output_type="comic",
        brief=Brief.model_validate(
            {**BRIEF_FIELDS, "character": {"appearance": "단발", "outfit": "니트"}}
        ),
        draft=ComicDraft(
            ad_plan="기획안 문장",
            panels=[
                Panel(index=index, role=role, scene=f"{index}번 장면", dialogue=f"대사 {index}")
                for index, role in enumerate(roles, start=1)
            ],
        ),
        spec=ImageSpec(width=3456, height=2304),
    )


def png_bytes(width: int = 32, height: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeImages:
    """`client.images.generate` 하나만 흉내냅니다."""

    def __init__(self, payload: bytes | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        encoded = base64.b64encode(self.payload or b"").decode() if self.payload else None
        return type("Response", (), {"data": [type("Datum", (), {"b64_json": encoded})()]})()


@pytest.fixture
def model_settings() -> Settings:
    return Settings(generation_mode="model", model_api_key="test-key")


def install(monkeypatch: pytest.MonkeyPatch, images: FakeImages) -> None:
    """`openai.OpenAI` 를 가로챕니다. `render` 가 지연 import 하므로 모듈에 심습니다."""
    module = type("OpenAiModule", (), {})()
    module.OpenAI = lambda **_: type("Client", (), {"images": images})()  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openai", module)


# ---- 프롬프트 ---------------------------------------------------------------------


def test_the_grounding_sentence_is_always_in_the_prompt() -> None:
    """⚠️ INV-6. 이 문장을 빼는 것은 프롬프트를 줄이는 일이 아니라 가드레일을 끄는 일입니다 -
    없는 효능을 그려 넣으면 표시광고법상 허위 과장 광고이고, on/off 델타가 보고 지표입니다."""
    for request in (single_ad_request(), comic_request()):
        assert render_prompt.GROUNDING in render_prompt.build(request)


def test_the_prompt_carries_the_evidence_not_just_the_copy() -> None:
    """근거는 `sellingPoint` 입니다. 카피만 보내면 무엇을 근거로 그렸는지가 사라집니다."""
    prompt = render_prompt.build(single_ad_request())

    assert "무향 무알코올, 두꺼운 원단" in prompt
    assert "한 장이면 충분해" in prompt


def test_the_ad_plan_is_not_sent_to_the_image_model() -> None:
    """⚠️ `adPlan` 은 기획 문장이지 그림에 쓸 글자가 아닙니다. 함께 보내면 모델이 기획서를
    이미지 안에 써 넣습니다."""
    assert "기획안 문장" not in render_prompt.build(single_ad_request())
    assert "기획안 문장" not in render_prompt.build(comic_request())


def test_an_empty_note_does_not_become_an_empty_instruction() -> None:
    """`""` 는 "비어 있음"입니다. 그대로 넣으면 모델에게 빈 요청을 지시하게 됩니다."""
    assert "추가 요청" not in render_prompt.build(single_ad_request())
    assert "추가 요청: 파란 톤" in render_prompt.build(single_ad_request(note="파란 톤"))


def test_the_comic_prompt_keeps_the_six_panel_grid_and_every_line() -> None:
    """검증 1순위가 통과시킨 조건입니다. 여기서 격자 지시가 빠지면 그 실험 결과가
    이 파이프라인으로 이전되지 않습니다."""
    prompt = render_prompt.build(comic_request())

    assert "3 x 2" in prompt
    for index in range(1, 7):
        assert f"대사 {index}" in prompt


# ---- 호출 -------------------------------------------------------------------------


def test_the_requested_size_is_what_gets_sent(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """호출자가 규격을 정해 보냅니다. 엔진이 유형을 보고 스스로 정하면 기획서 10.2 의 값이
    두 곳에 생깁니다 (미결정_대장 N16)."""
    images = FakeImages(payload=png_bytes())
    install(monkeypatch, images)

    render.render_image(comic_request(), model_settings)

    assert images.calls[0]["size"] == "3456x2304"
    assert images.calls[0]["n"] == 1


def test_quality_is_omitted_unless_it_is_configured(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 미지정이면 모델이 회차마다 티어를 골라 비용이 2.3배까지 벌어집니다 (2026-08-13 실측).
    그럼에도 기본값을 비워 두는 것은 받는 값이 확인되지 않았기 때문입니다 - 잘못된 값을 상수로
    박으면 모든 호출이 400 으로 죽습니다."""
    images = FakeImages(payload=png_bytes())
    install(monkeypatch, images)

    render.render_image(single_ad_request(), model_settings)
    assert "quality" not in images.calls[0]

    render.render_image(
        single_ad_request(),
        Settings(generation_mode="model", model_api_key="k", image_quality="high"),
    )
    assert images.calls[1]["quality"] == "high"


def test_the_result_is_lossless_webp_whatever_the_api_returned(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """계약이 내부 홉을 무손실 WebP 로 못 박습니다. 검증 1순위의 지표가 그려진 글자라, 손실
    압축을 한 번 거치면 채점이 압축 아티팩트를 재게 됩니다."""
    install(monkeypatch, FakeImages(payload=png_bytes(64, 64)))

    payload = render.render_image(single_ad_request(), model_settings)

    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WEBP"
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (64, 64)


# ---- 실패 -------------------------------------------------------------------------


def test_a_missing_key_fails_instead_of_falling_back_to_the_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ 키가 없다고 스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절).
    이 분기는 명시적으로 실패해야 하고, 그것이 ADR-0005 의 "폴백 없음"입니다."""
    images = FakeImages(payload=png_bytes())
    install(monkeypatch, images)

    with pytest.raises(render.RenderFailedError, match="ADGEN_MODEL_API_KEY"):
        render.render_image(single_ad_request(), Settings(generation_mode="model"))

    assert images.calls == []


def test_any_vendor_error_becomes_one_failure(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """인증 실패도 쿼터 초과도 타임아웃도 호출자에게는 같은 답입니다: 쓸 수 없음."""
    install(monkeypatch, FakeImages(error=RuntimeError("rate limit")))

    with pytest.raises(render.RenderFailedError, match="rate limit"):
        render.render_image(single_ad_request(), model_settings)


def test_a_url_response_is_refused_rather_than_downloaded(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """검증 1순위가 확인한 것은 인라인 base64 경로뿐입니다. URL 응답을 같은 것으로 취급하면
    확인한 적 없는 경로를 확인한 것처럼 다루게 됩니다."""
    install(monkeypatch, FakeImages(payload=None))

    with pytest.raises(render.RenderFailedError, match="b64_json"):
        render.render_image(single_ad_request(), model_settings)


def test_an_unreadable_response_is_a_failure_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    install(monkeypatch, FakeImages(payload=b"not an image at all"))

    with pytest.raises(render.RenderFailedError):
        render.render_image(single_ad_request(), model_settings)


def test_the_stub_branch_never_touches_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ 회귀 가드. 스텁 모드가 실수로 API 를 부르면 CI 가 돈을 씁니다."""
    images = FakeImages(error=AssertionError("스텁 모드는 모델을 부르면 안 됩니다"))
    install(monkeypatch, images)

    payload = render.render_image(single_ad_request(), Settings(generation_mode="stub"))

    assert payload[:4] == b"RIFF"
    assert images.calls == []

"""`image:render` 의 실물 분기 — 프롬프트 조립과 실패 처리.

⚠️ **외부 API 를 부르지 않습니다.** 호출 1회가 요금이고 CI 가 비결정적이 됩니다 (AGENTS.md).
여기서 검증하는 것은 "그림이 예쁜가"가 아니라 **우리가 무엇을 보내고 실패를 어떻게 다루는가**
이며, 둘 다 호출 없이 확인할 수 있는 성질입니다. 그림의 품질은 검증 1순위의 몫입니다.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from ai_engine import render, render_prompt
from ai_engine.config import Settings
from ai_engine.draft_prompt import ROLE_BEATS
from ai_engine.models import (
    PANEL_ROLES,
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
        quality="low",
    )


def comic_request(width: int = 3456, height: int = 2304) -> ImageRenderRequest:
    """⚠️ 기본값이 운영 규격입니다. 합성까지 도는 테스트는 **작은 캔버스**를 쓰세요 -
    3456 x 2304 는 약 8MP 라 칸 6장을 실제로 붙이면 테스트가 느려집니다. 격자 산술은 캔버스
    크기와 무관하므로 96 x 64 로 재도 같은 것을 잽니다."""
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
        spec=ImageSpec(width=width, height=height),
        quality="medium",
    )


def comic_panel(index: int = 1) -> Panel:
    """⚠️ 역할은 번호가 정합니다 (INV-5). 여기서 `role` 을 번호와 무관하게 고정하면 1 ~ 3번
    칸에 제품이 등장하는지 같은 성질을 이 픽스처로는 잴 수 없습니다 (이슈 #272)."""
    return Panel(
        index=index,
        role=PANEL_ROLES[index - 1],
        scene=f"{index}번 장면",
        dialogue=f"대사 {index}",
    )


def png_bytes(width: int = 32, height: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeImages:
    """`client.images.generate` 하나만 흉내냅니다."""

    def __init__(
        self,
        payload: bytes | None = None,
        error: Exception | None = None,
        block_until: threading.Event | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.block_until = block_until
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.block_until is not None:
            # 예산 초과를 흉내냅니다. `FakePanels` 와 같은 이유로 `sleep` 을 쓰지 않습니다.
            self.block_until.wait(timeout=30)
        if self.error is not None:
            raise self.error
        encoded = base64.b64encode(self.payload or b"").decode() if self.payload else None
        return type("Response", (), {"data": [type("Datum", (), {"b64_json": encoded})()]})()


PANEL_MARK = re.compile(r"전체 6칸 중 (\d)번 칸이다\.")


class FakePanels:
    """만화형 6회 호출을 흉내냅니다. `generate` 는 1번 칸, `edit` 는 나머지입니다.

    칸마다 **다른 색**을 돌려주는 것이 핵심입니다. 전부 같은 색이면 합성 위치가 뒤바뀌어도
    결과 픽셀이 같아서 배치를 검사할 수 없습니다. 어느 칸인지는 프롬프트에서 읽습니다 -
    호출 순서로 판단하면 병렬 경로에서 그 순서 자체가 보장되지 않습니다.
    """

    def __init__(
        self,
        fail_on: int | None = None,
        barrier: threading.Barrier | None = None,
        wrong_size_on: int | None = None,
        block_until: threading.Event | None = None,
        block_first_until: threading.Event | None = None,
    ) -> None:
        self.fail_on = fail_on
        self.barrier = barrier
        self.wrong_size_on = wrong_size_on
        self.block_until = block_until
        self.block_first_until = block_first_until
        self.lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []

    @staticmethod
    def color(index: int) -> tuple[int, int, int]:
        return (index * 40, 255 - index * 30, index * 10)

    def _answer(self, kwargs: dict[str, Any], *, edit: bool) -> Any:
        index = int(PANEL_MARK.search(kwargs["prompt"]).group(1))  # type: ignore[union-attr]
        with self.lock:
            self.calls.append(kwargs)
            if edit:
                self.edits.append(kwargs)
        if self.barrier is not None and edit:
            # 다섯이 다 도착해야 통과합니다. 순차로 돌면 첫 호출이 여기서 시간 초과로 깨지고,
            # 그것이 곧 "병렬이 아니다" 라는 판정입니다. sleep 으로 재면 느린 CI 에서 흔들립니다.
            self.barrier.wait()
        if self.block_until is not None and edit:
            # 예산 초과를 흉내냅니다. 테스트가 끝나면서 풀어 주므로 스레드가 남지 않습니다 -
            # 여기서 `sleep` 을 쓰면 그 시간만큼 세션 종료가 실제로 늦어집니다.
            self.block_until.wait(timeout=30)
        if self.block_first_until is not None and not edit:
            # 1번 칸만 붙잡습니다. `block_until` 과 나눈 이유는 예산이 걸리는 자리가 둘이고
            # (이슈 #180), 한쪽만 막아야 어느 자리가 끊었는지를 가릴 수 있기 때문입니다.
            self.block_first_until.wait(timeout=30)
        if index == self.fail_on:
            raise RuntimeError(f"{index}번 칸 벤더 오류")
        width, height = (int(part) for part in kwargs["size"].split("x"))
        if index == self.wrong_size_on:
            # 벤더가 요청한 크기를 안 지킨 경우. 성공 응답이라 호출부는 알아채지 못합니다.
            width, height = width - 16, height
        buffer = io.BytesIO()
        Image.new("RGB", (width, height), self.color(index)).save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return type("Response", (), {"data": [type("Datum", (), {"b64_json": encoded})()]})()

    def generate(self, **kwargs: Any) -> Any:
        return self._answer(kwargs, edit=False)

    def edit(self, **kwargs: Any) -> Any:
        return self._answer(kwargs, edit=True)


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
    없는 효능을 그려 넣으면 표시광고법상 허위 과장 광고이고, on/off 델타가 보고 지표입니다.

    ⚠️ **칸마다 확인합니다.** 만화형이 호출 6회로 갈라진 뒤로는 한 칸이라도 이 문장을 빠뜨리면
    그 칸에서 없는 효능이 나올 수 있고, 세트로 보면 여전히 한 장의 광고물입니다.
    """
    assert render_prompt.GROUNDING in render_prompt.build(single_ad_request())
    for index in range(1, 7):
        for with_reference in (False, True):
            prompt = render_prompt.build_panel(
                comic_request(), comic_panel(index), with_reference=with_reference
            )
            assert render_prompt.GROUNDING in prompt


def test_the_prompt_carries_the_evidence_not_just_the_copy() -> None:
    """근거는 `sellingPoint` 입니다. 카피만 보내면 무엇을 근거로 그렸는지가 사라집니다."""
    prompt = render_prompt.build(single_ad_request())

    assert "무향 무알코올, 두꺼운 원단" in prompt
    assert "한 장이면 충분해" in prompt


def test_the_ad_plan_is_not_sent_to_the_image_model() -> None:
    """⚠️ `adPlan` 은 기획 문장이지 그림에 쓸 글자가 아닙니다. 함께 보내면 모델이 기획서를
    이미지 안에 써 넣습니다."""
    assert "기획안 문장" not in render_prompt.build(single_ad_request())
    assert "기획안 문장" not in render_prompt.build_panel(
        comic_request(), comic_panel(), with_reference=False
    )


def test_an_empty_note_does_not_become_an_empty_instruction() -> None:
    """`""` 는 "비어 있음"입니다. 그대로 넣으면 모델에게 빈 요청을 지시하게 됩니다."""
    assert "추가 요청" not in render_prompt.build(single_ad_request())
    assert "추가 요청: 파란 톤" in render_prompt.build(single_ad_request(note="파란 톤"))


def test_a_panel_prompt_asks_for_one_scene_and_only_its_own_line() -> None:
    """⚠️ 칸 프롬프트가 격자를 지시하면 합성 뒤에 36칸이 됩니다.

    그리고 **자기 대사만** 들어가야 합니다. 여섯 대사를 다 보내면 모델이 한 칸에 다른 칸의
    문구까지 써 넣습니다 - 한 장 방식에서는 그것이 정상 지시였으므로 옮겨 오기 쉬운 실수입니다.
    """
    prompt = render_prompt.build_panel(comic_request(), comic_panel(3), with_reference=False)

    assert render_prompt.SINGLE_PANEL in prompt
    assert "3 x 2" not in prompt
    assert "대사 3" in prompt
    for other in (1, 2, 4, 5, 6):
        assert f"대사 {other}" not in prompt


def test_only_the_later_panels_are_told_to_keep_the_reference() -> None:
    """1번 칸은 레퍼런스가 될 그림 자체라 유지할 대상이 없습니다. 그 칸에 이 문장을 넣으면
    모델이 있지도 않은 입력 이미지를 따르라는 지시를 받습니다."""
    request = comic_request()

    assert render_prompt.KEEP_REFERENCE not in render_prompt.build_panel(
        request, comic_panel(1), with_reference=False
    )
    assert render_prompt.KEEP_REFERENCE in render_prompt.build_panel(
        request, comic_panel(2), with_reference=True
    )


def test_the_panel_role_reaches_the_image_prompt() -> None:
    """⚠️ 이슈 #272. 카피 쪽은 `draft_prompt` 가 역할을 알려 주고 받아 오는데 그림 쪽에는
    통로가 없었습니다. 그래서 `scene` 과 `dialogue` 는 기획서 7.3 을 따르는데 그림만 따르지
    않는 세트가 나옵니다 - 2026-08-26 실물 회차에서 1 ~ 3번 칸에 제품이 이미 놓였습니다."""
    request = comic_request()

    for index in range(1, 7):
        prompt = render_prompt.build_panel(request, comic_panel(index), with_reference=index > 1)

        assert ROLE_BEATS[PANEL_ROLES[index - 1]] in prompt


def test_the_product_is_not_drawn_before_the_solution_panel() -> None:
    """기획서 7.3 이 제품 등장을 4번 칸("제품 등장 및 해결")에 두었습니다. 1 ~ 3번은 후킹,
    상황 제시, 문제와 고민이라 그림에 제품이 있으면 문제에서 해결로 넘어가는 구조가 그림만
    보면 성립하지 않습니다.

    ⚠️ **제품명과 소구점은 앞 칸에도 그대로 갑니다.** 막는 것은 "그리지 마라" 하나이고,
    근거를 빼면 `GROUNDING` 이 검사할 대상이 사라집니다.
    """
    request = comic_request()

    for index in (1, 2, 3):
        prompt = render_prompt.build_panel(request, comic_panel(index), with_reference=index > 1)

        assert render_prompt.PRODUCT_NOT_YET in prompt
        assert BRIEF_FIELDS["productName"] in prompt
        assert render_prompt.GROUNDING in prompt

    for index in (4, 5, 6):
        prompt = render_prompt.build_panel(request, comic_panel(index), with_reference=True)

        assert render_prompt.PRODUCT_NOT_YET not in prompt


def test_the_reference_does_not_ask_to_keep_a_product_that_is_not_there() -> None:
    """⚠️ 1번 칸은 후킹이라 제품이 없습니다. 레퍼런스에 없는 것을 유지하라고 하면 모델이
    제품을 지어내 앞 칸에 그립니다 (이슈 #272).

    ⚠️ **대가가 있습니다** - 4 ~ 6번 칸의 포장 모양이 서로 고정되지 않습니다. 다섯 칸 모두
    1번 칸 하나를 레퍼런스로 보기 때문이고(ADR-0017 의 동시 호출), 고정하려면 제품 사진을
    두 번째 레퍼런스로 보내야 합니다. 이 시험은 그것까지 재지 않습니다.
    """
    assert "제품" not in render_prompt.KEEP_REFERENCE


def test_the_character_reaches_the_panel_that_has_no_reference() -> None:
    """⚠️ 1번 칸에 인물을 알려 줄 통로는 `brief.character` 뿐입니다. 나머지 칸은 1번 칸 그림을
    보고 그리지만 1번 칸은 볼 것이 없어서, 여기서 빠지면 세트마다 다른 사람이 나옵니다."""
    prompt = render_prompt.build_panel(comic_request(), comic_panel(1), with_reference=False)

    assert "단발" in prompt
    assert "니트" in prompt


def test_the_retired_whole_sheet_prompt_has_no_way_back() -> None:
    """⚠️ 한 장에 6칸은 ADR-0017 이 폐기한 방식입니다. 규격이 산술적으로 달성되지 않으므로
    (경계선을 그리는 한 칸은 1152px 보다 작아집니다) 조용히 되돌아갈 자리를 남기지 않습니다."""
    request = comic_request()

    with pytest.raises(TypeError, match="build_panel"):
        render_prompt.build(request)


# ---- 호출 -------------------------------------------------------------------------


def test_the_requested_size_is_what_gets_sent(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """호출자가 규격을 정해 보냅니다. 엔진이 유형을 보고 스스로 정하면 기획서 10.2 의 값이
    두 곳에 생깁니다 (미결정_대장 N16)."""
    images = FakeImages(payload=png_bytes())
    install(monkeypatch, images)

    render.render_image(single_ad_request(), model_settings)

    assert images.calls[0]["size"] == "1088x1088"
    assert images.calls[0]["n"] == 1


def test_the_panel_size_is_divided_out_of_the_requested_canvas() -> None:
    """⚠️ 1152 를 상수로 두지 않습니다. 계약이 보낸 캔버스를 3x2 로 나눠 얻습니다 - 같은
    숫자를 여기 또 적으면 한쪽만 고치는 순간 어긋납니다 (미결정_대장 N16).

    운영 규격 3456 x 2304 가 정확히 1152 x 1152 여섯 칸으로 나뉜다는 것이 ADR-0017 의 전제이고,
    한 장 생성 방식이 달성하지 못한 바로 그 값입니다 (실측 1101 ~ 1142px).
    """
    assert render._panel_size(ImageSpec(width=3456, height=2304)) == (1152, 1152)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1088, 1088, "나누어떨어지지"),  # 1088 / 3 이 정수가 아닙니다
        (96, 80, "16의 배수"),  # 96/3=32 는 되지만 80/2=40 이 16의 배수가 아닙니다
    ],
    ids=["격자로 안 나뉨", "칸이 16의 배수가 아님"],
)
def test_a_canvas_that_cannot_be_tiled_fails_before_any_call(
    width: int, height: int, expected: str
) -> None:
    """⚠️ 호출 **전에** 막습니다. 그대로 보내면 첫 칸이 400 으로 돌아오는데 그때는 이미 요금이
    나간 뒤이고, 나누어떨어지지 않는 쪽은 400 도 나지 않고 캔버스에 띠만 남습니다 - 그 띠가
    이 방식으로 없앤 "회차마다 흔들리는 여백" 입니다."""
    # ⚠️ `ImageSpec` 조립을 밖으로 뺍니다. 이것도 검증이 붙어 있어(16의 배수) 안에 두면
    # 어느 쪽이 던진 예외인지가 갈리지 않습니다.
    spec = ImageSpec(width=width, height=height)

    with pytest.raises(render.RenderFailedError, match=expected):
        render._panel_size(spec)


def test_the_request_decides_the_quality_tier(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """티어는 호출자가 출력 유형을 보고 정해 보냅니다 (계약 `ImageQuality`, 2026-08-20).

    이 서비스가 `output_type` 에서 유도하면 같은 결정이 두 곳에 생기고, `spec` 을 유도하지
    않는 이유와 똑같이 한쪽만 고치는 순간 어긋납니다. 값 자체의 정본은 backend 의
    `COMIC_QUALITY` / `SINGLE_AD_QUALITY` 입니다.
    """
    images = FakeImages(payload=png_bytes())
    install(monkeypatch, images)
    render.render_image(single_ad_request(), model_settings)

    panels = FakePanels()
    install(monkeypatch, panels)
    render.render_image(comic_request(96, 64), model_settings)

    assert images.calls[0]["quality"] == "low"
    assert {call["quality"] for call in panels.calls} == {"medium"}, "칸 6장이 같은 티어여야 합니다"


def test_the_tier_is_always_sent(monkeypatch: pytest.MonkeyPatch, model_settings: Settings) -> None:
    """⚠️ 싣지 않으면 모델이 회차마다 티어를 골라 같은 요청의 비용이 최대 9배까지 벌어집니다
    (2026-08-13, 08-15 실측). 그래서 계약이 `quality` 를 필수로 두고, 벤더의 `auto` 는
    열거에 없습니다."""
    images = FakeImages(payload=png_bytes())
    install(monkeypatch, images)

    render.render_image(single_ad_request(), model_settings)

    assert "quality" in images.calls[0]


def test_the_dev_override_wins_and_leaves_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """개발과 검증 실험을 `low` 로 돌리기 위한 스위치입니다 (생성_파이프라인 6.2절).

    ⚠️ 경고가 함께 남아야 합니다. 조용히 덮어쓰면 이 상태로 잰 숫자가 운영 경로의 숫자로
    보고됩니다 - 스텁을 측정값으로 읽는 것과 같은 사고입니다.
    """
    panels = FakePanels()
    install(monkeypatch, panels)
    settings = Settings(generation_mode="model", model_api_key="k", image_quality_override="low")

    with caplog.at_level(logging.WARNING, logger="ai_engine.render"):
        render.render_image(comic_request(96, 64), settings)

    assert {call["quality"] for call in panels.calls} == {"low"}
    assert "medium" in caplog.text, "덮어쓴 원래 티어가 로그에 남아야 합니다"
    assert caplog.text.count("ADGEN_IMAGE_QUALITY_OVERRIDE") == 1, (
        "칸마다 경고를 내면 세트 하나에 6줄이 쌓여 로그가 읽히지 않습니다"
    )


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


# ---- 만화형: 컷별 생성과 합성 (ADR-0017) ------------------------------------------


def test_a_comic_is_six_calls_with_the_first_panel_as_the_reference(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 1번 칸만 `generate` 이고 나머지 다섯은 `edit` 입니다.

    이 모양이 병렬의 근거입니다 - 2 ~ 6번이 서로가 아니라 **전부 1번 칸만** 레퍼런스로 쓰므로
    칸끼리 의존이 없습니다. 직전 칸을 넘기도록 바꾸면 의존이 생겨 병렬과 배타가 되고,
    ADR-0017 의 결정 자체가 뒤집힙니다.
    """
    panels = FakePanels()
    install(monkeypatch, panels)

    render.render_image(comic_request(96, 64), model_settings)

    assert len(panels.calls) == 6
    assert len(panels.edits) == 5
    references = {call["image"][0][1] for call in panels.edits}
    assert len(references) == 1, "다섯 칸이 같은 1번 칸을 봐야 합니다"
    assert {call["size"] for call in panels.calls} == {"32x32"}


def test_every_reference_is_a_separate_object(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 다섯 스레드가 열린 파일 객체 하나를 함께 읽으면 읽기 위치가 섞여 본문이 깨집니다.
    실험 하네스는 순차라 이 함정이 드러나지 않았습니다 - 바이트를 넘겨 SDK 가 각자 감싸게 합니다."""
    panels = FakePanels()
    install(monkeypatch, panels)

    render.render_image(comic_request(96, 64), model_settings)

    for call in panels.edits:
        assert isinstance(call["image"][0][1], bytes)


def test_the_five_later_panels_really_are_in_flight_together(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """A2. 순차로 돌면 `medium` 한 세트가 310.8초라 호출자의 300초 예산을 넘습니다.

    ⚠️ 시간을 재지 않고 **동시 도착**을 잽니다. 다섯이 모두 도착해야 장벽이 열리므로, 순차
    구현이면 첫 호출이 여기서 시간 초과로 깨집니다. `sleep` 으로 재는 방식은 느린 CI 에서
    흔들려서 결국 아무도 믿지 않는 테스트가 됩니다.
    """
    panels = FakePanels(barrier=threading.Barrier(5, timeout=10))
    install(monkeypatch, panels)

    render.render_image(comic_request(96, 64), model_settings)

    assert len(panels.edits) == 5


def test_the_panels_land_in_reading_order_with_no_gaps(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """계약의 `Panel.index` 가 3x2 배치 위치와 1:1 입니다 (왼쪽 위에서 오른쪽으로).

    ⚠️ **픽셀로 확인합니다.** "6칸이 균등한가" 를 Y/N 으로 보면 배치가 뒤바뀌어도 통과합니다 -
    한 장 생성 방식의 규격 미달이 30건 내내 안 잡힌 이유가 그것이었습니다. 여기서는 칸마다
    색을 달리하고 각 칸의 중앙 픽셀을 읽습니다.

    바깥 여백이 0px 인 것도 같은 방식으로 잡힙니다. 여백이 있으면 모서리 픽셀이 배경색입니다.
    """
    panels = FakePanels()
    install(monkeypatch, panels)

    payload = render.render_image(comic_request(96, 64), model_settings)

    with Image.open(io.BytesIO(payload)) as canvas:
        image = canvas.convert("RGB")
        assert image.size == (96, 64)
        for index in range(1, 7):
            column, row = (index - 1) % 3, (index - 1) // 3
            center = (column * 32 + 16, row * 32 + 16)
            assert image.getpixel(center) == FakePanels.color(index), f"{index}번 칸의 자리"
        for corner in ((0, 0), (95, 0), (0, 63), (95, 63)):
            assert image.getpixel(corner) != render.COMPOSE_BACKGROUND, "바깥 여백은 0px 입니다"


def test_the_composed_comic_is_lossless_webp(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """합성 단계가 생겨도 계약이 정한 형식은 그대로입니다. 검증 1순위가 채점하는 것이 칸에
    그려진 한글 글자라, 손실 압축을 한 번이라도 거치면 채점이 압축 아티팩트를 재게 됩니다."""
    install(monkeypatch, FakePanels())

    payload = render.render_image(comic_request(96, 64), model_settings)

    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WEBP"


def test_one_failed_panel_fails_the_whole_set(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """A3 / N20-a. 부분 재시도는 열지 않습니다 (ADR-0017).

    불완전한 세트를 내보내는 것보다 명시적으로 실패하는 편이 낫고, 이는 열화를 브리프 자동
    채움 하나로 한정한 ADR-0005 와 같은 방향입니다. **어느 칸이 깨졌는지는 메시지에 남습니다** -
    6회 호출 중 하나가 실패한 것이라, 그 정보가 없으면 로그만 보고는 재현할 수 없습니다.
    """
    install(monkeypatch, FakePanels(fail_on=4))
    request = comic_request(96, 64)

    with pytest.raises(render.RenderFailedError, match="4번 칸이 실패"):
        render.render_image(request, model_settings)


@pytest.mark.parametrize("wrong", [1, 5], ids=["1번 칸", "5번 칸"])
def test_a_panel_of_the_wrong_size_fails_instead_of_being_stretched(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, wrong: int
) -> None:
    """⚠️ **늘려 붙이면 규격 위반이 합성물에서는 통과로 보입니다** (PR #150 리뷰, 임동규).

    보정해도 캔버스는 3456 x 2304 로 맞아 떨어지므로, 픽셀을 재는 쪽은 "칸 1152px 정확"을
    확인했다고 판단합니다. 그 정확도를 만든 것은 생성 결과가 아니라 우리 `resize` 인데 말입니다.
    그리고 재샘플링은 칸에 그려진 한글을 뭉갭니다 - 검증 1순위가 채점하는 대상이 그 글자라,
    무손실 WebP 를 고집하는 이유가 여기에도 그대로 적용됩니다.

    **1번 칸은 부채꼴로 퍼지기 전에 걸립니다.** 그 칸은 나머지 다섯의 레퍼런스라, 합성
    단계까지 끌고 가면 다섯 호출의 요금이 다 나간 뒤에 같은 결론에 도달합니다.
    """
    panels = FakePanels(wrong_size_on=wrong)
    install(monkeypatch, panels)
    request = comic_request(96, 64)

    with pytest.raises(render.RenderFailedError, match=f"{wrong}번 칸이 16x32"):
        render.render_image(request, model_settings)

    assert len(panels.edits) == (0 if wrong == 1 else 5)


def test_a_failing_first_panel_never_fans_out(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """1번 칸이 실패하면 나머지 다섯은 레퍼런스가 없어 부를 수 없습니다. 그래도 부르면 요금이
    다섯 번 더 나가고 결과는 어차피 실패입니다."""
    panels = FakePanels(fail_on=1)
    install(monkeypatch, panels)
    request = comic_request(96, 64)

    with pytest.raises(render.RenderFailedError):
        render.render_image(request, model_settings)

    assert panels.edits == []


# ---- 타임아웃 예산 (이슈 #141) ------------------------------------------------------


def test_the_per_call_timeout_leaves_room_under_the_total_budget(
    env_example: dict[str, str],
) -> None:
    """⚠️ **두 값은 함께 움직여야 합니다.** 만화형은 1번 칸 뒤에 병렬 배치가 오는 두 단계라
    최악 대기가 칸당 상한의 2배입니다. 그 2배가 총 예산을 넘으면 예산이 먼저 끊어 놓고도 칸은
    계속 돌게 되고, 총 예산이 호출자의 `render_timeout_s`(300초)를 넘으면 애초에 이 설계가
    막으려던 상태 - 호출자가 먼저 끊는 상태 - 로 돌아갑니다 (이슈 #141).

    ⚠️ 호출자 쪽 값도 `infra/.env.example` 에서 읽습니다. 상수로 적으면 그 값이 움직여도
    시험이 초록이라 짝의 절반만 고정됩니다 (이슈 #180 리뷰).
    """
    per_call = float(env_example["ADGEN_IMAGE_TIMEOUT_S"])
    total = float(env_example["ADGEN_RENDER_BUDGET_S"])
    caller = float(env_example["ADGEN_RENDER_TIMEOUT_S"])

    assert per_call * 2 <= total
    assert total < caller, "호출자의 render_timeout_s 보다 작아야 합니다"
    assert Settings.model_fields["image_timeout_s"].default == per_call
    assert Settings.model_fields["render_budget_s"].default == total


def test_the_per_call_timeout_reaches_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """설정만 내려도 클라이언트에 전달되지 않으면 아무 일도 하지 않습니다."""
    seen: dict[str, Any] = {}

    def client(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return type("Client", (), {"images": FakeImages(payload=png_bytes())})()

    module = type("OpenAiModule", (), {})()
    module.OpenAI = client  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openai", module)

    render.render_image(single_ad_request(), Settings(generation_mode="model", model_api_key="k"))

    assert seen["timeout"] == 120.0


def test_the_sdk_is_told_not_to_retry_behind_our_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ **넘기지 않으면 SDK 기본값 2 가 붙습니다** (이슈 #180).

    `openai` 는 타임아웃도 재시도하므로 (`_base_client` 가 `httpx.TimeoutException` 을 잡아
    `_sleep_for_retry` 뒤 `continue`), 호출 1회가 최대 3회 시도가 되고 `timeout=` 은 벽시계가
    아니라 **시도당** 상한이 됩니다. 그러면 120 x 3 = 360 이 호출자의 300 을 넘어,
    2026-08-21 회의록 04절이 확정한 순서 - 엔진이 먼저 포기한다 - 가 뒤집힙니다.
    """
    seen: dict[str, Any] = {}

    def client(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return type("Client", (), {"images": FakeImages(payload=png_bytes())})()

    module = type("OpenAiModule", (), {})()
    module.OpenAI = client  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openai", module)

    render.render_image(single_ad_request(), Settings(generation_mode="model", model_api_key="k"))

    assert seen["max_retries"] == 0


def test_a_slow_single_ad_is_cut_at_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """단일 광고형도 예산을 지납니다 (이슈 #180).

    호출이 하나뿐이라 이 경로를 지켜 주던 것은 `image_timeout_s`(120) < `render_timeout_s`(300)
    라는 산술뿐이었고, 그것은 `timeout=` 이 벽시계일 때만 성립합니다 - httpx 는
    connect/read/write 를 **각각** 잽니다. 산술은 값을 고치는 순간 사라지고 예산은 남습니다.
    """
    release = threading.Event()
    images = FakeImages(payload=png_bytes(), block_until=release)
    module = type("OpenAiModule", (), {})()
    module.OpenAI = lambda **_: type("Client", (), {"images": images})()  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openai", module)
    settings = Settings(generation_mode="model", model_api_key="k", render_budget_s=0.2)
    request = single_ad_request()

    started = time.monotonic()
    try:
        with pytest.raises(render.RenderFailedError, match="예산 안에 그림이"):
            render.render_image(request, settings)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert elapsed < 10.0, "붙잡힌 호출을 끝까지 기다렸습니다 - 예산이 집행되지 않은 것입니다"


def test_a_slow_panel_fails_the_set_without_waiting_for_the_stragglers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 의 대가. 병렬 배치가 예산을 넘기면 **기다리기를 그만두고** 세트를 버립니다.

    ⚠️ 사는 것은 "호출자가 먼저 끊지 않는 것" 하나입니다. 이미 나간 요청은 벤더 쪽에서 계속
    돌고 요금도 나갑니다. 그래도 이쪽이 나은 이유는, 호출자가 먼저 끊으면 실패의 이유를 아는
    쪽이 아무도 없기 때문입니다 (이슈 #141).

    ⚠️ **기다리지 않는다는 것까지 검사합니다.** `ThreadPoolExecutor` 를 `with` 로 쓰면
    `__exit__` 이 `shutdown(wait=True)` 라, 예산을 넘겨 빠져나갈 때도 남은 스레드를 끝까지
    기다립니다 - 그러면 예산이 아무 일도 하지 않고 증상은 똑같습니다.
    """
    release = threading.Event()
    install(monkeypatch, FakePanels(block_until=release))
    settings = Settings(generation_mode="model", model_api_key="k", render_budget_s=0.2)
    request = comic_request(96, 64)

    started = time.monotonic()
    try:
        with pytest.raises(render.RenderFailedError, match="예산 안에"):
            render.render_image(request, settings)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert elapsed < 10.0, "남은 칸을 기다렸습니다 - 예산이 집행되지 않은 것입니다"


def test_a_slow_first_panel_never_fans_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """1번 칸까지 예산을 다 썼으면 나머지 다섯은 부르지 않습니다. 불러 봐야 예산 안에 끝날 수
    없고 요금만 다섯 번 더 나갑니다.

    ⚠️ 예산 0 에서는 **기다림이 끊기는 경로와 돌아온 뒤 걸리는 경로 둘 다** 성립합니다
    (이슈 #180 이후). 어느 쪽이 이길지는 스레드 기동 속도에 달렸으므로 두 메시지가 공유하는
    문장으로 검사합니다 - 검사하려는 성질은 "부채꼴로 퍼지지 않는다" 하나입니다.
    """
    panels = FakePanels()
    install(monkeypatch, panels)
    settings = Settings(generation_mode="model", model_api_key="k", render_budget_s=0.0)
    request = comic_request(96, 64)

    with pytest.raises(render.RenderFailedError, match="나머지 칸은 부르지 않습니다"):
        render.render_image(request, settings)

    assert panels.edits == []


def test_a_hanging_first_panel_is_cut_at_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """1번 칸도 **예산 안에서** 기다립니다 (이슈 #180).

    이 칸은 데드라인 감쌈 없는 동기 호출이었고, 예산 확인은 그 호출이 **돌아온 뒤**였습니다.
    즉 돌아오지 않으면 예산이 아무 일도 하지 않았고, 그동안 총 예산이 실제로 걸린 자리는
    2 ~ 6번 칸뿐이었습니다.
    """
    release = threading.Event()
    panels = FakePanels(block_first_until=release)
    install(monkeypatch, panels)
    settings = Settings(generation_mode="model", model_api_key="k", render_budget_s=0.2)
    request = comic_request(96, 64)

    started = time.monotonic()
    try:
        with pytest.raises(render.RenderFailedError, match="예산 안에 1번 칸이"):
            render.render_image(request, settings)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert elapsed < 10.0, "붙잡힌 1번 칸을 끝까지 기다렸습니다 - 예산이 집행되지 않은 것입니다"
    assert panels.edits == [], "1번 칸이 오지도 않았는데 나머지 다섯을 불렀습니다"


# ---- 실패 -------------------------------------------------------------------------


def test_a_missing_key_fails_instead_of_falling_back_to_the_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ 키가 없다고 스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절).
    이 분기는 명시적으로 실패해야 하고, 그것이 ADR-0005 의 "폴백 없음"입니다."""
    images = FakeImages(payload=png_bytes())
    install(monkeypatch, images)
    request, keyless = single_ad_request(), Settings(generation_mode="model")

    with pytest.raises(render.RenderFailedError, match="ADGEN_MODEL_API_KEY"):
        render.render_image(request, keyless)

    assert images.calls == []


def test_any_vendor_error_becomes_one_failure(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """인증 실패도 쿼터 초과도 타임아웃도 호출자에게는 같은 답입니다: 쓸 수 없음."""
    install(monkeypatch, FakeImages(error=RuntimeError("rate limit")))
    request = single_ad_request()

    with pytest.raises(render.RenderFailedError, match="rate limit"):
        render.render_image(request, model_settings)


def test_a_url_response_is_refused_rather_than_downloaded(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """검증 1순위가 확인한 것은 인라인 base64 경로뿐입니다. URL 응답을 같은 것으로 취급하면
    확인한 적 없는 경로를 확인한 것처럼 다루게 됩니다."""
    install(monkeypatch, FakeImages(payload=None))
    request = single_ad_request()

    with pytest.raises(render.RenderFailedError, match="b64_json"):
        render.render_image(request, model_settings)


def test_an_unreadable_response_is_a_failure_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    install(monkeypatch, FakeImages(payload=b"not an image at all"))
    request = single_ad_request()

    with pytest.raises(render.RenderFailedError):
        render.render_image(request, model_settings)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (SimpleNamespace(data=[]), "data 가 비어"),
        (SimpleNamespace(data=None), "data 가 비어"),
        (SimpleNamespace(), "data 가 비어"),
        (SimpleNamespace(data=[SimpleNamespace(b64_json="QUJD1")]), "해독하지 못했습니다"),
        (SimpleNamespace(data=[SimpleNamespace(b64_json=12345)]), "해독하지 못했습니다"),
    ],
    ids=["data=[]", "data=None", "data 없음", "b64 패딩 깨짐", "b64_json 이 문자열이 아님"],
)
def test_a_misshapen_response_is_a_failure_not_a_crash(response: Any, expected: str) -> None:
    """⚠️ **어떤 실패인지보다 어떤 종류의 예외인지가 중요한 자리입니다.**

    라우트는 `RenderFailedError` 와 `NotImplementedError` 만 503 으로 바꿉니다. 전에는 이
    다섯 갈래가 `IndexError` · `TypeError` · `binascii.Error` 로 새어 나가 **500** 이
    되었습니다 (2026-08-18 실측) - 계약이 이 경로에 준 실패 코드는 503 하나인데도 말입니다.
    잡히지 않은 예외는 스택 트레이스까지 함께 나가므로 증상도 "엔진이 터졌다"로 보입니다.
    """
    with pytest.raises(render.RenderFailedError, match=expected):
        render._inline_bytes(response)


def test_base64_padding_survives_the_round_trip(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """위의 거절이 정상 응답까지 막지 않는지 봅니다. 거절만 검사하면 전부 거절해도 통과합니다."""
    install(monkeypatch, FakeImages(payload=png_bytes()))

    payload = render.render_image(single_ad_request(), model_settings)

    assert payload[:4] == b"RIFF"


def test_the_stub_branch_never_touches_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ 회귀 가드. 스텁 모드가 실수로 API 를 부르면 CI 가 돈을 씁니다."""
    images = FakeImages(error=AssertionError("스텁 모드는 모델을 부르면 안 됩니다"))
    install(monkeypatch, images)

    payload = render.render_image(single_ad_request(), Settings(generation_mode="stub"))

    assert payload[:4] == b"RIFF"
    assert images.calls == []

"""`brief:fill` 의 실물 분기 — 프롬프트 조립과 실패 처리.

⚠️ **외부 API 를 부르지 않습니다.** 호출 1회가 요금이고 CI 가 비결정적이 됩니다 (AGENTS.md).
여기서 확인하는 것은 "추론이 맞았는가"가 아니라 **무엇을 보내고 응답을 어떻게 다루는가**이며,
둘 다 호출 없이 확인할 수 있는 성질입니다.

⚠️ **`pytest.raises` 블록 안에는 검사 대상 호출 하나만 둡니다.** 요청을 그 안에서 만들면 만들다
난 실패로도 테스트가 통과하고, 그러면 정작 분기가 안 터지게 되어도 아무도 모릅니다
(`test_seams.py` 가 같은 이유로 같은 규칙을 씁니다).
"""

from __future__ import annotations

import base64
import io
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_engine import brief_fill, brief_prompt, service
from ai_engine.config import Settings
from ai_engine.service_schemas import BriefFillRequest

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPEG = b"\xff\xd8\xff" + b"0" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 20
WAV = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"0" * 20
"""⚠️ WebP 와 앞 네 바이트가 같습니다. `RIFF` 는 컨테이너 서명이지 WebP 의 서명이 아닙니다."""


def fill_request(payload: bytes = PNG, **overrides: Any) -> BriefFillRequest:
    """`model_construct` 로 만듭니다 - `UploadFile` 은 라우트가 만드는 객체입니다.

    필요한 것은 `.file.read()` 뿐이라 `BytesIO` 를 든 자리표시자면 충분하고, Starlette 의
    업로드 객체를 흉내 내기 시작하면 테스트가 프레임워크를 검사하게 됩니다.
    """
    fields: dict[str, Any] = {
        "product_image": SimpleNamespace(file=io.BytesIO(payload)),
        "product_name": "순한 대나무 물티슈",
        "selling_point": "무향 무알코올, 두꺼운 원단",
        "note": "",
    }
    fields.update(overrides)
    return BriefFillRequest.model_construct(**fields)


class FakeCompletions:
    """`client.chat.completions.create` 하나만 흉내냅니다."""

    def __init__(
        self,
        body: str | None = None,
        error: Exception | None = None,
        block_until: threading.Event | None = None,
    ) -> None:
        self.body = body
        self.error = error
        self.block_until = block_until
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.block_until is not None:
            # 예산 초과를 흉내냅니다. 테스트가 끝나면서 풀어 주므로 스레드가 남지 않습니다 -
            # 여기서 `sleep` 을 쓰면 그 시간만큼 세션 종료가 실제로 늦어집니다.
            self.block_until.wait(timeout=30)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=self.body)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def install(monkeypatch: pytest.MonkeyPatch, completions: FakeCompletions) -> dict[str, Any]:
    """`openai.OpenAI` 를 가로챕니다. `brief_fill` 이 지연 import 하므로 모듈에 심습니다.

    돌려주는 dict 에는 **클라이언트 생성 인자**가 담깁니다. 호출 인자가 아니라 그쪽을 봐야
    하는 값이 있기 때문입니다 - 타임아웃과 재시도 횟수가 그렇습니다 (이슈 #180).
    """
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    seen: dict[str, Any] = {}

    def factory(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return client

    module = SimpleNamespace(OpenAI=factory)
    monkeypatch.setitem(__import__("sys").modules, "openai", module)
    return seen


@pytest.fixture
def model_settings() -> Settings:
    return Settings(generation_mode="model", model_api_key="test-key")


DECIDED = '{"category": "생활용품", "target": "30대 주부"}'


# ---- 프롬프트 ---------------------------------------------------------------------


def test_the_prompt_offers_a_way_out_instead_of_forcing_an_answer() -> None:
    """⚠️ 거절 갈래가 빠지면 모델은 사진이 무엇인지 몰라도 그럴듯한 카테고리를 지어냅니다.

    그 값은 브리프에 저장되어 나중에 카피의 근거처럼 읽히는데 정작 아무 근거도 없습니다
    (기획서 9.3, 생성_파이프라인 5.2절).
    """
    assert "needsInput" in brief_prompt.SYSTEM
    assert "지어내지" in brief_prompt.SYSTEM


def test_an_empty_note_does_not_become_an_empty_instruction() -> None:
    """`""` 는 "비어 있음"입니다. 그대로 넣으면 모델에게 빈 요청을 지시하게 됩니다."""
    assert "자유 메모" not in brief_prompt.build_user("이름", "소구점", "")
    assert "자유 메모: 파란 톤" in brief_prompt.build_user("이름", "소구점", "파란 톤")


def test_the_prompt_is_versioned() -> None:
    """판 없는 프롬프트 변경은 그 이전 실측을 전부 무효로 만듭니다 (생성_파이프라인 4절)."""
    assert brief_prompt.VERSION


# ---- 호출 -------------------------------------------------------------------------


def test_the_photo_travels_inline_with_the_text(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """사진을 읽는 호출입니다 (생성_파이프라인 1절 1단계). 글만 보내면 추론이 아니라 짐작입니다."""
    completions = FakeCompletions(body=DECIDED)
    install(monkeypatch, completions)

    brief_fill.fill_brief(fill_request(), model_settings)

    parts = completions.calls[0]["messages"][1]["content"]
    kinds = [part["type"] for part in parts]
    assert kinds == ["text", "image_url"]
    assert "무향 무알코올, 두꺼운 원단" in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1]) == PNG


@pytest.mark.parametrize(
    ("payload", "media_type"),
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")],
    ids=["png", "jpeg", "webp"],
)
def test_the_format_comes_from_the_bytes_not_from_the_caller(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, payload: bytes, media_type: str
) -> None:
    """⚠️ `Content-Type` 도 파일 이름도 호출자가 실어 보내는 값이라, 믿으면 형식 검사가
    아무것도 검사하지 않게 됩니다 (backend 의 `backend_core.images` 가 같은 이유로 같은
    방식을 씁니다)."""
    completions = FakeCompletions(body=DECIDED)
    install(monkeypatch, completions)

    brief_fill.fill_brief(fill_request(payload), model_settings)

    url = completions.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith(f"data:{media_type};base64,")


def test_a_decided_answer_carries_no_needs_input(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    install(monkeypatch, FakeCompletions(body=DECIDED))

    response = brief_fill.fill_brief(fill_request(), model_settings)

    assert response.category == "생활용품"
    assert response.target == "30대 주부"
    assert "needsInput" not in response.model_dump(by_alias=True)


def test_not_deciding_is_a_normal_answer_not_an_error(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 추론이 돌았는데 판단이 서지 않은 것은 대화의 한 걸음입니다 (API_계약 4절).

    의존이 죽어서 응답이 아예 오지 않은 것(`messageMode: degraded`)과 다르고, 화면은 두
    경우를 `needsInput` 키의 유무로 가릅니다.
    """
    install(
        monkeypatch, FakeCompletions(body='{"needsInput": {"reason": "무엇인지 모르겠습니다"}}')
    )

    response = brief_fill.fill_brief(fill_request(), model_settings)

    assert response.needs_input is not None
    assert response.needs_input.reason == "무엇인지 모르겠습니다"
    assert (response.category, response.target) == ("", "")


def test_the_field_to_fill_is_ours_to_decide_not_the_models(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 회복 경로는 자유 메모 하나입니다 (기획서 9.3). 모델이 필드 이름을 고르게 두면
    화면이 매핑할 수 없는 이름이 - 그것도 회차마다 다른 이름이 - 계약을 타고 나갑니다."""
    body = '{"needsInput": {"field": "productImageUrl", "reason": "사진이 흐립니다"}}'
    install(monkeypatch, FakeCompletions(body=body))

    response = brief_fill.fill_brief(fill_request(), model_settings)

    assert response.needs_input is not None
    assert response.needs_input.field == brief_fill.NEEDS_INPUT_FIELD == "note"


# ---- 실패 -------------------------------------------------------------------------


def test_a_missing_key_fails_instead_of_falling_back_to_the_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ 키가 없다고 스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절).

    열화는 호출자가 합니다 - 이 서비스가 대신 열화하면 호출자는 열화한 줄 모릅니다 (ADR-0005).
    """
    completions = FakeCompletions(body=DECIDED)
    install(monkeypatch, completions)
    request, keyless = fill_request(), Settings(generation_mode="model")

    with pytest.raises(brief_fill.BriefFillFailedError, match="ADGEN_MODEL_API_KEY"):
        brief_fill.fill_brief(request, keyless)

    assert completions.calls == []


def test_any_vendor_error_becomes_one_failure(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """인증 실패도 쿼터 초과도 타임아웃도 호출자에게는 같은 답입니다: 쓸 수 없음."""
    install(monkeypatch, FakeCompletions(error=RuntimeError("rate limit")))
    request = fill_request()

    with pytest.raises(brief_fill.BriefFillFailedError, match="rate limit"):
        brief_fill.fill_brief(request, model_settings)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("이건 JSON 이 아닙니다", "JSON 이 아닙니다"),
        ('["생활용품"]', "객체가 아닙니다"),
        ('{"category": "생활용품"}', "거절 형식도 아닙니다"),
        ('{"category": "", "target": ""}', "거절 형식도 아닙니다"),
        ('{"needsInput": {}}', "reason 이 없습니다"),
    ],
    ids=["JSON 아님", "객체 아님", "타겟 없음", "둘 다 빈 문자열", "reason 없음"],
)
def test_a_half_answer_is_a_failure_not_a_polite_needs_input(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, body: str, expected: str
) -> None:
    """⚠️ 형식을 지키지 않은 응답을 거절로 바꿔 주면, 우리 쪽 응답 처리가 부족했던 것을
    사용자에게 "메모를 더 써 달라"고 떠넘기게 됩니다."""
    install(monkeypatch, FakeCompletions(body=body))
    request = fill_request()

    with pytest.raises(brief_fill.BriefFillFailedError, match=expected):
        brief_fill.fill_brief(request, model_settings)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (SimpleNamespace(choices=[]), "choices 가 없습니다"),
        (SimpleNamespace(choices=None), "choices 가 없습니다"),
        (SimpleNamespace(), "choices 가 없습니다"),
        (SimpleNamespace(choices=[SimpleNamespace(message=None)]), "본문이 비어"),
        (
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))]),
            "본문이 비어",
        ),
    ],
    ids=["choices=[]", "choices=None", "choices 없음", "message 없음", "content=None"],
)
def test_a_misshapen_response_is_a_failure_not_a_crash(response: Any, expected: str) -> None:
    """⚠️ **어떤 실패인지보다 어떤 종류의 예외인지가 중요한 자리입니다.**

    라우트는 `BriefFillFailedError` 만 503 으로 바꿉니다. `IndexError` 와 `TypeError` 로
    새어 나가면 **500** 이 되는데, 계약이 이 경로에 준 실패 코드는 503 하나입니다
    (`render._inline_bytes` 가 같은 사고로 고쳐졌습니다, 2026-08-18).
    """
    with pytest.raises(brief_fill.BriefFillFailedError, match=expected):
        brief_fill._content(response)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"GIF89a" + b"0" * 16, "형식을 알 수 없습니다"),
        (WAV, "형식을 알 수 없습니다"),
        (b"RIFF", "형식을 알 수 없습니다"),
        (b"", "비어 있습니다"),
    ],
    ids=["GIF 는 계약 밖", "RIFF 지만 WAV", "RIFF 뿐이고 잘림", "빈 파일"],
)
def test_an_image_the_contract_does_not_accept_never_reaches_the_vendor(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, payload: bytes, expected: str
) -> None:
    """계약이 받는 것은 JPEG, PNG, WebP 뿐입니다. 걸러 내지 않으면 요금이 나간 뒤에 실패합니다.

    ⚠️ `RIFF` 두 줄이 요점입니다 (PR #145 리뷰). 앞 네 바이트만 보면 WAV 와 AVI 가
    `image/webp` 로 이름 붙어 올라가, 바이트에서 형식을 알아낸다는 이 함수의 목적 자체가
    사라집니다. 형식 이름은 오프셋 8 의 `WEBP` 가 정합니다.
    """
    completions = FakeCompletions(body=DECIDED)
    install(monkeypatch, completions)
    request = fill_request(payload)

    with pytest.raises(brief_fill.BriefFillFailedError, match=expected):
        brief_fill.fill_brief(request, model_settings)

    assert completions.calls == []


def test_an_oversized_photo_never_reaches_the_vendor(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """호출자가 이미 검사한 값이지만, 여기서 안 보면 상한을 넘는 사진이 그대로 올라갑니다."""
    completions = FakeCompletions(body=DECIDED)
    install(monkeypatch, completions)
    request = fill_request(PNG + b"0" * brief_fill.MAX_IMAGE_BYTES)

    with pytest.raises(brief_fill.BriefFillFailedError, match="상한"):
        brief_fill.fill_brief(request, model_settings)

    assert completions.calls == []


def test_a_real_upload_reaches_the_vendor_through_the_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ 위 테스트들의 자리표시자가 증명하지 못하는 한 가지입니다.

    라우트가 넘기는 것은 Starlette 의 `UploadFile` 이고, 그 안은 `SpooledTemporaryFile`
    입니다. `.file.read()` 대신 코루틴을 만드는 실수는 목으로는 드러나지 않고 실제 업로드에서만
    빈 바이트로 나타납니다.
    """
    completions = FakeCompletions(body=DECIDED)
    install(monkeypatch, completions)
    monkeypatch.setattr(
        service, "settings", lambda: Settings(generation_mode="model", model_api_key="test-key")
    )

    response = TestClient(service.app).post(
        "/v1/brief:fill",
        data={"productName": "순한 대나무 물티슈", "sellingPoint": "무향 무알코올"},
        files={"productImage": ("a.png", PNG, "image/png")},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"category": "생활용품", "target": "30대 주부"}
    url = completions.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == PNG


def test_a_failed_inference_is_a_503_not_a_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """호출자에게는 계약에 있는 상태여야 합니다. 500 을 받으면 화면이 분기할 근거가 없고,
    열화(`messageMode: degraded`)와 우리 결함이 로그에서도 구분되지 않습니다."""
    install(monkeypatch, FakeCompletions(error=RuntimeError("rate limit")))
    monkeypatch.setattr(
        service, "settings", lambda: Settings(generation_mode="model", model_api_key="test-key")
    )

    response = TestClient(service.app).post(
        "/v1/brief:fill",
        data={"productName": "순한 대나무 물티슈", "sellingPoint": "무향 무알코올"},
        files={"productImage": ("a.png", PNG, "image/png")},
    )

    assert response.status_code == 503, response.text


def test_the_stub_branch_never_touches_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ 회귀 가드. 스텁 모드가 실수로 API 를 부르면 CI 가 돈을 씁니다."""
    completions = FakeCompletions(error=AssertionError("스텁 모드는 모델을 부르면 안 됩니다"))
    install(monkeypatch, completions)

    response = brief_fill.fill_brief(fill_request(), Settings(generation_mode="stub"))

    assert "STUB" in response.category
    assert completions.calls == []


# ---- 타임아웃 예산 (이슈 #180) --------------------------------------------------------


def test_the_sdk_is_told_not_to_retry_behind_our_budget(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ **세 이음매 중 이 자리가 가장 급합니다** (이슈 #180).

    `openai` 는 타임아웃도 재시도하므로 (`DEFAULT_MAX_RETRIES == 2`), 넘기지 않으면 12초가
    **시도당** 상한이 되고 최악 36초가 호출자의 15초를 넘깁니다. 그러면 호출자가 먼저 끊고
    이 이음매는 열화로 빠지는데(ADR-0005), 엔진은 죽지 않았고 느렸을 뿐입니다 - 사용자에게는
    같은 증상이지만 `messageMode: degraded` 비율은 벤더가 느렸던 날의 숫자가 되고, **그 값은
    보고 지표입니다.**
    """
    seen = install(monkeypatch, FakeCompletions(body=DECIDED))

    brief_fill.fill_brief(fill_request(), model_settings)

    assert seen["max_retries"] == 0
    assert seen["timeout"] == model_settings.brief_fill_model_timeout_s


def test_the_engine_gives_up_before_the_caller_does(env_example: dict[str, str]) -> None:
    """확정된 것은 값이 아니라 **순서**입니다 (2026-08-21 회의록 04절).

    호출자의 `ADGEN_BRIEF_FILL_TIMEOUT_S`(15초)와 같은 이름을 쓰지 않는 이유도 여기 있습니다 -
    `infra/.env` 한 줄이 양쪽을 함께 움직이면 이 부등호가 조용히 등호가 됩니다.

    ⚠️ **두 값을 다 `infra/.env.example` 에서 읽습니다.** 호출자 쪽을 상수로 적으면 그 값이
    움직여도 시험이 초록이라, docstring 이 막겠다는 바로 그 경우를 못 잡습니다. 그리고 맨
    `Settings()` 는 주변 환경변수를 읽으므로 판정이 셸에 좌우됩니다 - 코드 기본값은 필드
    선언에서 직접 꺼냅니다 (이슈 #180 리뷰).
    """
    engine = float(env_example["ADGEN_BRIEF_FILL_MODEL_TIMEOUT_S"])
    caller = float(env_example["ADGEN_BRIEF_FILL_TIMEOUT_S"])

    assert engine < caller, "엔진이 호출자보다 먼저 포기해야 합니다"
    assert Settings.model_fields["brief_fill_model_timeout_s"].default == engine, (
        "코드 기본값이 배포 값과 다릅니다 - 설정을 안 준 배포가 다른 순서로 돕니다"
    )


def test_a_hanging_call_is_cut_at_the_budget(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """벽시계는 우리가 잽니다 (이슈 #180 리뷰).

    `timeout=` 은 httpx 값이라 connect/read/write 를 **각각** 잽니다. SDK 재시도를 껐어도 한
    번의 시도가 12초를 넘을 수 있고, 그러면 호출자(15초)가 먼저 끊습니다. 이 이음매는 그때
    열화로 빠지므로 - 죽은 것이 아니라 느렸을 뿐인데 - `messageMode: degraded` 비율이
    부풀립니다. **그 값이 보고 지표라 서비스 동작만이 아니라 측정이 틀어집니다.**
    """
    release = threading.Event()
    install(monkeypatch, FakeCompletions(body=DECIDED, block_until=release))
    settings = model_settings.model_copy(update={"brief_fill_model_timeout_s": 0.2})
    request = fill_request()

    started = time.monotonic()
    try:
        with pytest.raises(brief_fill.BriefFillFailedError, match="예산 안에"):
            brief_fill.fill_brief(request, settings)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert elapsed < 10.0, "붙잡힌 호출을 끝까지 기다렸습니다 - 예산이 집행되지 않은 것입니다"

"""`draft:generate` 와 `draft:patch` 의 실물 분기 — 프롬프트 조립과 실패 처리.

⚠️ **외부 API 를 부르지 않습니다.** 호출 1회가 요금이고 CI 가 비결정적이 됩니다 (AGENTS.md).
여기서 확인하는 것은 "카피가 좋은가"가 아니라 **무엇을 보내고 응답을 어떻게 다루는가**입니다.
카피 품질은 `eval/` 의 지표 함수와 검증 회차의 몫입니다.

⚠️ **`pytest.raises` 블록 안에는 검사 대상 호출 하나만 둡니다.** 요청을 그 안에서 만들면 만들다
난 실패로도 테스트가 통과하고, 그러면 정작 분기가 안 터지게 되어도 아무도 모릅니다
(`test_seams.py` 가 같은 이유로 같은 규칙을 씁니다).
"""

from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace
from typing import Any

import pytest

from ai_engine import draft, draft_prompt
from ai_engine.config import Settings
from ai_engine.models import (
    PANEL_ROLES,
    Brief,
    ComicDraft,
    DraftGenerateRequest,
    DraftPatch,
    DraftPatchEngineRequest,
    OutputType,
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
CHARACTER = {"appearance": "단발", "outfit": "니트"}


def brief(**overrides: object) -> Brief:
    return Brief.model_validate({**BRIEF_FIELDS, **overrides})


def comic_brief(**overrides: object) -> Brief:
    return brief(character=CHARACTER, **overrides)


def generate_request(
    output_type: OutputType = "single_ad", **overrides: Any
) -> DraftGenerateRequest:
    fields: dict[str, Any] = {
        "output_type": output_type,
        "brief": comic_brief() if output_type == "comic" else brief(),
    }
    fields.update(overrides)
    return DraftGenerateRequest(**fields)


def single_ad_draft() -> SingleAdDraft:
    return SingleAdDraft(ad_plan="기획안 문장", ad_copy="원래 카피", visual_plan="원래 비주얼")


def comic_draft() -> ComicDraft:
    return ComicDraft(
        ad_plan="기획안 문장",
        panels=[
            Panel(index=index, role=role, scene=f"{index}번 장면", dialogue=f"대사 {index}")
            for index, role in enumerate(PANEL_ROLES, start=1)
        ],
    )


def patch_request(**patch_fields: object) -> DraftPatchEngineRequest:
    return DraftPatchEngineRequest(
        output_type="single_ad",
        brief=brief(),
        draft=single_ad_draft(),
        patch=DraftPatch.model_validate(patch_fields),
    )


def comic_patch_request(**patch_fields: object) -> DraftPatchEngineRequest:
    return DraftPatchEngineRequest(
        output_type="comic",
        brief=comic_brief(),
        draft=comic_draft(),
        patch=DraftPatch.model_validate(patch_fields),
    )


class FakeCompletions:
    """`client.chat.completions.create` 하나만 흉내냅니다.

    `then` 은 **두 번째 호출부터** 돌려줄 본문입니다. 가드레일이 1회 재생성을 하므로 회차별로
    다른 답을 줄 수 있어야 하고, 그래야 "재생성이 실제로 다시 물어봤는가"를 볼 수 있습니다.
    """

    def __init__(
        self,
        body: str | None = None,
        error: Exception | None = None,
        then: str | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.bodies = [body] if then is None else [body, then]
        self.error = error
        self.delay_s = delay_s
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.delay_s:
            # ⚠️ 여기서만 `sleep` 을 씁니다. 검사 대상이 "예산이 두 시도에 걸쳐 있는가" 라
            # **시간이 쌓이는 것 자체**가 검사 내용이고, 이벤트로는 그것을 못 만듭니다.
            time.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        body = self.bodies[min(len(self.calls) - 1, len(self.bodies) - 1)]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])

    def prompt_at(self, index: int) -> str:
        return str(self.calls[index]["messages"][0]["content"])


def install(monkeypatch: pytest.MonkeyPatch, completions: FakeCompletions) -> dict[str, Any]:
    """`openai.OpenAI` 를 가로챕니다. `draft` 가 지연 import 하므로 모듈에 심습니다.

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


SINGLE_AD_BODY = json.dumps(
    {"adPlan": "새 기획안", "copy": "새 카피", "visualPlan": "새 비주얼"}, ensure_ascii=False
)
COMIC_BODY = json.dumps(
    {
        "adPlan": "새 기획안",
        "panels": [{"scene": f"장면 {i}", "dialogue": f"대사 {i}"} for i in range(1, 7)],
    },
    ensure_ascii=False,
)
REFUSAL_BODY = '{"refusal": "no_evidence"}'


# ---- 프롬프트 ---------------------------------------------------------------------


def test_the_guardrail_block_is_in_the_prompt_by_default() -> None:
    """⚠️ INV-6. 이 블록을 빼는 것은 프롬프트를 줄이는 일이 아니라 가드레일을 절반 끄는
    일입니다 - 없는 효능을 쓰면 표시광고법상 허위 과장 광고입니다 (생성_파이프라인 5.1절)."""
    for prompt in (
        draft_prompt.build_generate(generate_request()),
        draft_prompt.build_generate(generate_request("comic")),
        draft_prompt.build_patch(patch_request(copy="더 짧게")),
    ):
        assert draft_prompt.GUARDRAIL_BLOCK in prompt


def test_turning_the_guardrail_off_actually_turns_it_off() -> None:
    """⚠️ 대조군의 정의입니다 (생성_파이프라인 5.3절). 금지 사항을 켠 채로 "가드레일 끔"이라고
    보고하면 환각 억제율이 0 으로 나올 수밖에 없고, 그것이 보고 지표 자체를 무효로 만듭니다.

    근거 블록은 남습니다 - 근거 없이 쓰라는 뜻이 아니라 금지 지시 없이 쓰라는 뜻입니다.
    """
    prompt = draft_prompt.build_generate(generate_request(guardrail_applied=False))

    assert draft_prompt.GUARDRAIL_BLOCK not in prompt
    assert draft_prompt.EVIDENCE_HEADING in prompt
    assert "무향 무알코올, 두꺼운 원단" in prompt


def test_the_inferred_values_sit_outside_the_evidence_block() -> None:
    """⚠️ `category` 와 `target` 은 추론값이라 근거가 아닙니다 (생성_파이프라인 5.2절).

    근거 블록 안에 넣으면 금지 사항이 무력해집니다 - 추론으로 채운 카테고리를 근거 삼아 효능을
    쓰면 지어낸 것인데, 프롬프트상으로는 근거를 지킨 것처럼 보이기 때문입니다.
    """
    prompt = draft_prompt.build_generate(generate_request())
    evidence = prompt[prompt.index(draft_prompt.EVIDENCE_HEADING) : prompt.index("</근거>")]

    assert "무향 무알코올, 두꺼운 원단" in evidence
    assert "생활용품" not in evidence
    assert "30대 주부" not in evidence
    assert "[추론 결과]" in prompt


def test_the_assembly_order_follows_the_document() -> None:
    """생성_파이프라인 4절의 표가 프롬프트의 정본입니다. 순서가 어긋나면 문서가 프롬프트를
    설명하지 못하게 됩니다."""
    prompt = draft_prompt.build_generate(generate_request("comic"))
    order = [
        "당신은 제품 정보만",
        "[표현 가이드라인과 금지 사항]",
        draft_prompt.EVIDENCE_HEADING,
        "[추론 결과]",
        "[화풍]",
        "[유형별 지시]",
        "[출력 규격]",
    ]
    positions = [prompt.index(marker) for marker in order]

    assert positions == sorted(positions), prompt


def test_the_comic_prompt_carries_the_six_beats_in_order() -> None:
    """기획서 7.3 의 컷별 역할 템플릿입니다. `index` 가 `role` 을 정하고 사용자는 고르지
    않습니다 (INV-5)."""
    prompt = draft_prompt.build_generate(generate_request("comic"))
    positions = [prompt.index(f"{index}번 칸: ") for index in range(1, 7)]

    assert positions == sorted(positions)
    assert draft_prompt.ROLE_BEATS["hook"] in prompt
    assert "단발" in prompt, "만화형 브리프의 인물이 프롬프트에 실려야 합니다"


def test_the_comic_prompt_stages_the_product_from_the_first_panel() -> None:
    """⚠️ 2026-08-29 실물 회차. 장면(`scene`)이 1번 칸을 제품 없는 후킹으로 쓰면, 그 칸을
    레퍼런스로 보는 나머지 다섯 칸에서 제품과 장소가 칸마다 달라집니다.

    ⚠️ 렌더 쪽 지시(`render_prompt`)와 **한 쌍입니다.** 여기서 "가방에서 꺼낸다" 는 장면이
    나오면 그림 쪽 규칙과 정면으로 부딪힙니다.
    """
    prompt = draft_prompt.build_generate(generate_request("comic"))

    assert draft_prompt.PRODUCT_STAGING in prompt
    assert f"{draft_prompt.PRODUCT_USED_AT_INDEX}번 칸" in prompt


def test_the_comic_prompt_states_the_dialogue_length_hint() -> None:
    """N18 (2026-08-21 회의 확정). 상한은 **프롬프트 지침으로만** 존재합니다.

    ⚠️ 이 테스트가 고정하는 것은 "지침이 프롬프트에 있다" 뿐입니다. 출력이 25자를 넘겼을 때
    거부하거나 재생성하는 검사 코드는 **일부러 없습니다** - 회의가 그렇게 정했습니다. 나중에
    검사를 붙이자는 제안이 오면 그 결정을 뒤집는 회의록이 먼저 필요합니다.
    """
    prompt = draft_prompt.build_generate(generate_request("comic"))

    assert f"{draft_prompt.DIALOGUE_LENGTH_HINT}자를 넘기지 마세요" in prompt
    assert "공백과 문장부호를 포함해" in prompt, "세는 방식이 빠지면 지침이 해석에 열립니다"


def test_the_prompt_asks_for_the_changed_field_only() -> None:
    """⚠️ 전체를 다시 쓰게 하지 않습니다 (생성_파이프라인 3절). 전체 재생성 후 diff 를 취하는
    방식은 지정하지 않은 자리까지 조용히 바꿉니다."""
    prompt = draft_prompt.build_patch(patch_request(copy="더 짧게"))

    assert '{"copy": "<새 카피>"}' in prompt
    assert "visualPlan" not in prompt.split("[출력 규격]")[-1]
    assert "원래 비주얼" in prompt, "바꾸지 않을 부분도 맥락으로는 보여 줍니다"


def test_the_prompt_is_versioned() -> None:
    """판 없는 프롬프트 변경은 그 이전 실측을 전부 무효로 만듭니다 (생성_파이프라인 4절)."""
    assert draft_prompt.VERSION


# ---- 생성 -------------------------------------------------------------------------


def test_a_single_ad_draft_comes_back_whole(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    install(monkeypatch, FakeCompletions(body=SINGLE_AD_BODY))

    response = draft.generate_draft(generate_request(), model_settings)

    assert isinstance(response.draft, SingleAdDraft)
    assert response.draft.ad_copy == "새 카피"
    assert response.guardrail_applied is True
    assert "refusalReason" not in response.model_dump(by_alias=True)


def test_the_comic_branch_writes_six_real_panels(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 스텁이 만화형을 거절하는 것과 다릅니다 (구현_범위 1절). 칸 수와 역할은 계약과
    기획서 7.3 이 정해 두었으므로 실물 분기가 여기서 새로 정하는 값이 없습니다."""
    install(monkeypatch, FakeCompletions(body=COMIC_BODY))

    response = draft.generate_draft(generate_request("comic"), model_settings)

    assert isinstance(response.draft, ComicDraft)
    assert [panel.index for panel in response.draft.panels] == [1, 2, 3, 4, 5, 6]


def test_the_roles_are_ours_to_assign_not_the_models(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ INV-5. 모델이 보낸 `index` 와 `role` 은 읽지 않습니다 - 물어보면 여섯 박자가 기획
    근거가 아니라 회차마다 흔들리는 값이 됩니다."""
    body = json.dumps(
        {
            "adPlan": "새 기획안",
            "panels": [
                {"index": 9, "role": "cta", "scene": f"장면 {i}", "dialogue": f"대사 {i}"}
                for i in range(1, 7)
            ],
        },
        ensure_ascii=False,
    )
    install(monkeypatch, FakeCompletions(body=body))

    response = draft.generate_draft(generate_request("comic"), model_settings)

    assert isinstance(response.draft, ComicDraft)
    assert [panel.role for panel in response.draft.panels] == list(PANEL_ROLES)


def test_a_refusal_is_a_normal_answer_with_no_draft(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 거절은 200 입니다 - 쓸 수 있었는데 지어내지 않고 물러선 상태입니다.

    `draft` 키가 **없어야** 하고 `null` 이면 안 됩니다. 계약에 `null` 은 어디에도 없습니다.
    """
    install(monkeypatch, FakeCompletions(body=REFUSAL_BODY))

    response = draft.generate_draft(generate_request(), model_settings)
    body = response.model_dump(by_alias=True)

    assert response.refusal_reason == "no_evidence"
    assert "draft" not in body
    assert body["guardrailApplied"] is True


def test_the_control_flag_survives_a_refusal(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """`guardrailApplied` 는 거절 여부와 무관하게 항상 실립니다. 대조 실행과 검증된 출력이
    구분되지 않으면 환각 억제율 자체를 계산할 수 없습니다."""
    install(monkeypatch, FakeCompletions(body=REFUSAL_BODY))

    response = draft.generate_draft(generate_request(guardrail_applied=False), model_settings)

    assert response.guardrail_applied is False


def test_a_guardrail_refusal_cannot_come_from_the_model(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ `refusalReason: guardrail` 은 **재생성 1회 뒤에도** 근거 밖 주장이 남은 경우입니다
    (생성_파이프라인 5.1.1절). 출력 검증이 이 경로에 붙기 전까지 그 판정은 존재할 수 없고,
    모델이 스스로 그렇게 말해도 검증을 거친 판정이 아닙니다."""
    install(monkeypatch, FakeCompletions(body='{"refusal": "guardrail"}'))
    request = generate_request()

    with pytest.raises(draft.DraftFailedError, match="알 수 없는 거절 사유"):
        draft.generate_draft(request, model_settings)


# ---- 부분 교체 ---------------------------------------------------------------------


def test_the_patch_changes_only_what_it_names(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 부분 교체와 전체 재생성을 가르는 성질입니다. 카피를 바꿔 달라고 한 사용자는 이미
    승인한 비주얼 구성안을 들고 있고, 그것까지 다시 쓰면 사용자의 결정이 사라집니다."""
    install(monkeypatch, FakeCompletions(body=SINGLE_AD_BODY))

    response = draft.patch_draft(patch_request(copy="더 짧게"), model_settings)

    assert isinstance(response.draft, SingleAdDraft)
    assert response.draft.ad_copy == "새 카피"
    assert response.draft.visual_plan == "원래 비주얼"
    assert response.draft.ad_plan == "기획안 문장"


def test_what_the_model_returns_outside_the_patch_is_ignored(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 응답으로 시안을 만들지 않고 원문을 복사해 지정된 자리만 덮어씁니다. 모델이 손대지
    말라고 한 필드까지 돌려주더라도 그것은 읽히지 않습니다 - 응답 모양이 같아서 조용히 바뀝니다."""
    install(monkeypatch, FakeCompletions(body=SINGLE_AD_BODY))

    response = draft.patch_draft(patch_request(copy="더 짧게"), model_settings)

    assert isinstance(response.draft, SingleAdDraft)
    assert response.draft.visual_plan == "원래 비주얼", "응답의 '새 비주얼'이 새면 안 됩니다"
    assert response.draft.ad_plan == "기획안 문장", "adPlan 은 읽기 전용입니다 (INV-8)"


def test_a_comic_patch_touches_only_the_named_cell(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """패치에 없는 칸은 손대지 않고, 있는 칸이라도 이름 없는 부분은 그대로 둡니다."""
    body = json.dumps({"panels": {"4": {"dialogue": "새 대사"}}}, ensure_ascii=False)
    install(monkeypatch, FakeCompletions(body=body))

    response = draft.patch_draft(
        comic_patch_request(panels={"4": {"dialogue": "더 짧게"}}), model_settings
    )

    assert isinstance(response.draft, ComicDraft)
    assert response.draft.panels[3].dialogue == "새 대사"
    assert response.draft.panels[3].scene == "4번 장면", "장면은 주문에 없었습니다"
    assert response.draft.panels[0].dialogue == "대사 1"
    assert [panel.role for panel in response.draft.panels] == list(PANEL_ROLES)


def test_an_empty_replacement_is_applied_rather_than_ignored(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """`""` 는 "비워라" 라는 정상 지시입니다 (계약 3절). 값으로 판단하면 "그대로 둬라" 와
    뭉개집니다."""
    install(monkeypatch, FakeCompletions(body='{"visualPlan": ""}'))

    response = draft.patch_draft(patch_request(visualPlan=""), model_settings)

    assert isinstance(response.draft, SingleAdDraft)
    assert response.draft.visual_plan == ""
    assert response.draft.ad_copy == "원래 카피"


def test_a_patch_refusal_omits_the_draft_rather_than_echoing_it(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 원문 유지는 호출자가 합니다 - 호출자가 보낸 그 시안입니다. 원문을 되돌려 보내면서
    `refusalReason` 을 함께 실으면 계약이 말하는 거절(`draft` 키가 없는 상태)이 아니게 됩니다."""
    install(monkeypatch, FakeCompletions(body=REFUSAL_BODY))

    response = draft.patch_draft(patch_request(copy="더 짧게"), model_settings)

    assert response.refusal_reason == "no_evidence"
    assert "draft" not in response.model_dump(by_alias=True)


# ---- 실패 -------------------------------------------------------------------------


def test_a_missing_key_fails_instead_of_falling_back_to_the_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ 키가 없다고 스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절).
    이 이음매에 폴백은 없습니다 - 카피는 제품마다 달라 사전 승인 응답이 성립하지 않습니다."""
    completions = FakeCompletions(body=SINGLE_AD_BODY)
    install(monkeypatch, completions)
    request, keyless = generate_request(), Settings(generation_mode="model")

    with pytest.raises(draft.DraftFailedError, match="ADGEN_MODEL_API_KEY"):
        draft.generate_draft(request, keyless)

    assert completions.calls == []


def test_any_vendor_error_becomes_one_failure(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """인증 실패도 쿼터 초과도 타임아웃도 호출자에게는 같은 답입니다: 쓸 수 없음."""
    install(monkeypatch, FakeCompletions(error=RuntimeError("rate limit")))
    request = generate_request()

    with pytest.raises(draft.DraftFailedError, match="rate limit"):
        draft.generate_draft(request, model_settings)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("이건 JSON 이 아닙니다", "JSON 이 아닙니다"),
        ('["카피"]', "객체가 아닙니다"),
        ('{"adPlan": "기획안"}', "형식이 아닙니다"),
        ('{"adPlan": "기획안", "copy": "카피", "visualPlan": 3}', "형식이 아닙니다"),
        ('{"adPlan": "기획안", "copy": "카피", "visualPlan": "비주얼", "extra": "x"}', "형식이"),
    ],
    ids=["JSON 아님", "객체 아님", "필드 누락", "문자열 아님", "모르는 키"],
)
def test_a_malformed_draft_is_a_failure_not_a_salvage_attempt(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, body: str, expected: str
) -> None:
    """⚠️ 깨진 응답에서 문장을 건져 내면, 그렇게 얻은 문자열은 모델이 쓴 카피가 아니라 우리가
    주운 조각이고 근거 안에 있는지 아무도 확인하지 않았습니다."""
    install(monkeypatch, FakeCompletions(body=body))
    request = generate_request()

    with pytest.raises(draft.DraftFailedError, match=expected):
        draft.generate_draft(request, model_settings)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('{"adPlan": "기획안", "panels": {}}', "배열이 아닙니다"),
        ('{"adPlan": "기획안", "panels": []}', "6개 고정"),
        ('{"adPlan": "기획안", "panels": [{"scene": "1", "dialogue": "1"}]}', "6개 고정"),
    ],
    ids=["배열 아님", "빈 배열", "칸 부족"],
)
def test_a_comic_that_is_not_six_cells_is_refused(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, body: str, expected: str
) -> None:
    """0 도 7 도 유효하지 않습니다 (INV-1). 여섯 박자가 기획의 근거 자체입니다."""
    install(monkeypatch, FakeCompletions(body=body))
    request = generate_request("comic")

    with pytest.raises(draft.DraftFailedError, match=expected):
        draft.generate_draft(request, model_settings)


def test_a_patch_answer_missing_the_named_cell_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """조용히 원문을 두면 호출자는 200 을 받고 아무것도 바뀌지 않은 시안을 봅니다 - 이 경로가
    가장 가지면 안 되는 실패 모양입니다 (2026-08-18 실측과 같은 사고)."""
    install(monkeypatch, FakeCompletions(body='{"panels": {"2": {"dialogue": "엉뚱한 칸"}}}'))
    request = comic_patch_request(panels={"4": {"dialogue": "더 짧게"}})

    with pytest.raises(draft.DraftFailedError, match="4번 칸의 응답이 없습니다"):
        draft.patch_draft(request, model_settings)


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

    라우트는 `DraftFailedError` 와 `NotImplementedError` 만 503 으로 바꿉니다. `IndexError`
    와 `TypeError` 로 새어 나가면 **500** 이 되는데, 계약이 이 경로에 준 실패 코드는 503
    하나입니다 (`render._inline_bytes` 가 같은 사고로 고쳐졌습니다, 2026-08-18).
    """
    with pytest.raises(draft.DraftFailedError, match=expected):
        draft._content(response)


def test_the_stub_branch_never_touches_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ 회귀 가드. 스텁 모드가 실수로 API 를 부르면 CI 가 돈을 씁니다."""
    completions = FakeCompletions(error=AssertionError("스텁 모드는 모델을 부르면 안 됩니다"))
    install(monkeypatch, completions)

    response = draft.generate_draft(generate_request(), Settings(generation_mode="stub"))

    assert response.draft is not None
    assert completions.calls == []


# ---- 가드레일 출력 검증 (ADR-0019, 생성_파이프라인 5.1절) --------------------------------


def body_with_copy(copy: str) -> str:
    return json.dumps(
        {"adPlan": "새 기획안", "copy": copy, "visualPlan": "새 비주얼"}, ensure_ascii=False
    )


CLEAN_COPY = "무향 무알코올, 두꺼운 원단"
VIOLATING_COPY = "타사보다 2배 두꺼운 원단"


def test_a_clean_draft_is_not_regenerated(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 재생성은 위반이 있을 때만입니다. 매번 두 번 부르면 텍스트 비용이 두 배가 됩니다."""
    completions = FakeCompletions(body=body_with_copy(CLEAN_COPY))
    install(monkeypatch, completions)

    response = draft.generate_draft(generate_request(), model_settings)

    assert response.draft is not None
    assert len(completions.calls) == 1


def test_the_first_violation_is_regenerated_and_never_reaches_the_caller(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """생성_파이프라인 5.1.1절: 1회차 위반은 조용히 재생성하고 클라이언트에 보이지 않습니다."""
    completions = FakeCompletions(
        body=body_with_copy(VIOLATING_COPY), then=body_with_copy(CLEAN_COPY)
    )
    install(monkeypatch, completions)

    response = draft.generate_draft(generate_request(), model_settings)

    assert len(completions.calls) == 2
    assert isinstance(response.draft, SingleAdDraft)
    assert response.draft.ad_copy == CLEAN_COPY
    assert "refusalReason" not in response.model_dump(by_alias=True)


def test_the_regeneration_prompt_names_what_was_caught(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ "규칙을 어겼다" 만 알려 주면 모델이 같은 문장을 다시 씁니다. 그러면 재생성 1회가
    요금만 쓰고 끝납니다."""
    completions = FakeCompletions(
        body=body_with_copy(VIOLATING_COPY), then=body_with_copy(CLEAN_COPY)
    )
    install(monkeypatch, completions)

    draft.generate_draft(generate_request(), model_settings)

    retry = completions.prompt_at(1)
    assert "타사" in retry
    assert "2배" in retry
    assert "타사 비교" in retry, "갈래도 한국어로 보여 줍니다"
    assert completions.prompt_at(0) in retry, "원래 지시문 위에 덧붙입니다"


def test_a_violation_surviving_one_regeneration_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 계약의 `refusalReason: guardrail` 이 정확히 이 상태입니다 - 재생성 1회 뒤에도
    근거 밖 주장이 남은 경우. 200 이고 `draft` 가 빠집니다."""
    completions = FakeCompletions(body=body_with_copy(VIOLATING_COPY))
    install(monkeypatch, completions)

    response = draft.generate_draft(generate_request(), model_settings)
    body = response.model_dump(by_alias=True)

    assert response.refusal_reason == "guardrail"
    assert "draft" not in body
    assert body["guardrailApplied"] is True


def test_the_regeneration_happens_exactly_once(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 열어 두면 거절이 반복될 때 비용이 무한히 늘고, 그 비용은 사용자가 기다리는 시간이기도
    합니다. 위반이 계속돼도 호출은 두 번에서 멈춰야 합니다."""
    completions = FakeCompletions(body=body_with_copy(VIOLATING_COPY))
    install(monkeypatch, completions)

    draft.generate_draft(generate_request(), model_settings)

    assert len(completions.calls) == 2


def test_the_control_run_does_not_verify_at_all(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ `guardrailApplied: false` 는 대조군입니다 (생성_파이프라인 5.3절). 검사도 재생성도
    하지 않아야 그 실행이 "가드레일 없이 뽑은 결과" 가 됩니다 - 조용히 검사하면 델타가 0 이
    나오고 보고 지표가 무효가 됩니다."""
    completions = FakeCompletions(body=body_with_copy(VIOLATING_COPY))
    install(monkeypatch, completions)

    response = draft.generate_draft(generate_request(guardrail_applied=False), model_settings)

    assert len(completions.calls) == 1
    assert isinstance(response.draft, SingleAdDraft)
    assert response.draft.ad_copy == VIOLATING_COPY
    assert response.guardrail_applied is False


def test_the_production_instructions_are_not_verified(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ `adPlan` 과 `visualPlan` 은 소비자에게 하는 주장이 아니라 제작 지시문입니다.

    검사에 넣으면 "가장 잘 보이는 위치" 같은 평범한 지시가 최상급 위반으로 잡혀 전량 거절이
    됩니다 (2026-08-20 실측, ADR-0019).
    """
    body = json.dumps(
        {
            "adPlan": "가장 잘 보이는 위치에 배치해 타사 대비 우위를 시각화한다",
            "copy": CLEAN_COPY,
            "visualPlan": "화면의 최상단에 제품을 둔다",
        },
        ensure_ascii=False,
    )
    completions = FakeCompletions(body=body)
    install(monkeypatch, completions)

    response = draft.generate_draft(generate_request(), model_settings)

    assert response.draft is not None, "지시문의 표현은 거절 사유가 아닙니다"
    assert len(completions.calls) == 1


def test_the_comic_dialogue_is_what_gets_checked(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """만화형에서 이미지에 그려지는 글자는 여섯 칸의 대사입니다. `scene` 은 지시문입니다."""
    panels = [{"scene": f"장면 {i}", "dialogue": f"대사 {i}"} for i in range(1, 7)]
    panels[3]["dialogue"] = "타사보다 2배 좋아요"
    completions = FakeCompletions(
        body=json.dumps({"adPlan": "기획안", "panels": panels}, ensure_ascii=False)
    )
    install(monkeypatch, completions)

    response = draft.generate_draft(generate_request("comic"), model_settings)

    assert response.refusal_reason == "guardrail"
    assert len(completions.calls) == 2


def test_the_patch_path_is_guarded_too(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """생성_파이프라인 2절의 흐름도가 PATCH 를 다시 가드레일로 보냅니다. 부분 교체로 근거 밖
    주장을 밀어 넣을 수 있으면 시안 생성 쪽 검사는 우회로가 생긴 셈입니다."""
    completions = FakeCompletions(body=json.dumps({"copy": VIOLATING_COPY}, ensure_ascii=False))
    install(monkeypatch, completions)

    response = draft.patch_draft(patch_request(copy="더 세게"), model_settings)

    assert response.refusal_reason == "guardrail"
    assert "draft" not in response.model_dump(by_alias=True)
    assert len(completions.calls) == 2


def test_a_number_the_user_typed_is_not_our_invention(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ 근거에 있는 수치를 카피가 되풀이하는 것은 지어낸 것이 아닙니다. 이것을 잡으면
    사용자가 직접 쓴 소구점을 광고에 쓸 수 없게 됩니다."""
    completions = FakeCompletions(body=body_with_copy("3겹 원단으로 든든하게"))
    install(monkeypatch, completions)
    request = DraftGenerateRequest(
        output_type="single_ad", brief=brief(sellingPoint="3겹 원단, 두툼합니다")
    )

    response = draft.generate_draft(request, model_settings)

    assert response.draft is not None
    assert len(completions.calls) == 1


# ---- 사용량 기록 --------------------------------------------------------------------


def usage_seams(caplog: pytest.LogCaptureFixture) -> list[str]:
    """`usage` 줄에서 이음매 꼬리표만 순서대로."""
    return [
        message.split("seam=")[1].split(" ")[0]
        for message in caplog.messages
        if message.startswith("usage ")
    ]


def test_each_call_is_recorded_under_its_own_seam(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """⚠️ 총량만 남기면 어디를 줄여야 하는지 알 수 없습니다. 회차당 비용이 이음매마다 다릅니다
    (생성_파이프라인 1절 - 변동 비용이 생기는 곳은 부분 교체뿐입니다)."""
    install(monkeypatch, FakeCompletions(body=body_with_copy(CLEAN_COPY)))

    with caplog.at_level(logging.INFO, logger="ai_engine.draft"):
        draft.generate_draft(generate_request(), model_settings)
        draft.patch_draft(patch_request(copy="더 짧게"), model_settings)

    assert usage_seams(caplog) == ["draft:generate", "draft:patch"]


def test_the_regeneration_is_counted_separately(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """⚠️ 재생성이 본 호출과 같은 꼬리표로 섞이면 **가드레일이 예산에서 차지하는 몫을 잴 수
    없습니다.** 그 몫이 D2 대조 실험에서 on 팔과 off 팔을 가르는 값입니다."""
    install(
        monkeypatch,
        FakeCompletions(body=body_with_copy(VIOLATING_COPY), then=body_with_copy(CLEAN_COPY)),
    )

    with caplog.at_level(logging.INFO, logger="ai_engine.draft"):
        draft.generate_draft(generate_request(), model_settings)

    assert usage_seams(caplog) == ["draft:generate", "draft:generate:retry"]


# ---- 타임아웃 예산 (이슈 #180) --------------------------------------------------------


def test_the_sdk_is_told_not_to_retry_behind_our_budget(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """넘기지 않으면 SDK 기본값 2 가 붙어 50초가 **시도당** 상한이 되고, 최악 150초가 호출자의
    60초를 넘깁니다 (이슈 #180). 이쪽은 열화가 없어 실패가 실패로 보이지만, 호출자가 먼저
    끊으면 어디서 막혔는지를 아는 쪽이 아무도 없습니다.
    """
    seen = install(monkeypatch, FakeCompletions(body=SINGLE_AD_BODY))

    draft.generate_draft(generate_request(), model_settings)

    assert seen["max_retries"] == 0
    assert seen["timeout"] == model_settings.draft_model_timeout_s


def test_the_engine_gives_up_before_the_caller_does(env_example: dict[str, str]) -> None:
    """확정된 것은 값이 아니라 **순서**입니다 (2026-08-21 회의록 04절).

    ⚠️ 두 값을 다 `infra/.env.example` 에서 읽는 이유는 `test_brief_fill_model.py` 의 같은
    시험과 같습니다 - 호출자 쪽을 상수로 적으면 짝의 절반만 고정됩니다 (이슈 #180 리뷰).
    """
    engine = float(env_example["ADGEN_DRAFT_MODEL_TIMEOUT_S"])
    caller = float(env_example["ADGEN_DRAFT_TIMEOUT_S"])

    assert engine < caller, "엔진이 호출자보다 먼저 포기해야 합니다"
    assert Settings.model_fields["draft_model_timeout_s"].default == engine, (
        "코드 기본값이 배포 값과 다릅니다 - 설정을 안 준 배포가 다른 순서로 돕니다"
    )


def test_the_budget_covers_the_guardrail_retry_too(
    monkeypatch: pytest.MonkeyPatch, model_settings: Settings
) -> None:
    """⚠️ **예산이 두 시도를 함께 덮습니다** (이슈 #180 리뷰).

    시도마다 새로 시작하면 요청 하나가 최악 100초인데 호출자(`ADGEN_DRAFT_TIMEOUT_S`)는
    60초입니다. SDK 재시도를 껐어도 풀리지 않습니다 - **우리 자신의 재생성이 두 번째
    시도**이기 때문이고, 이것은 예외 경로가 아니라 D2 대조 실험의 on 팔입니다.

    각 시도는 예산 안에 들고 합계만 넘깁니다. 시도별 예산이면 통과할 배치이므로, 이 시험이
    보는 것은 정확히 "예산이 시도에 걸쳐 있는가" 하나입니다.
    """
    completions = FakeCompletions(
        body=body_with_copy(VIOLATING_COPY), then=body_with_copy(CLEAN_COPY), delay_s=0.2
    )
    install(monkeypatch, completions)
    settings = model_settings.model_copy(update={"draft_model_timeout_s": 0.3})
    request = generate_request()

    with pytest.raises(draft.DraftFailedError, match="예산 안에"):
        draft.generate_draft(request, settings)

    assert len(completions.calls) == 2, "재생성까지 갔다가 합계에서 끊긴 것이어야 합니다"

"""S4 시안 생성과 S5 부분 교체 이음매 — the ad plan and copy the user reviews.

⚠️ **The stub and the real implementation are two branches of the same function**
(구현_범위 1.1절). Filling in `_generate_with_model` is the whole of the real work.

Two rules this module must not "simplify":

- **No fallback.** Copy differs per product, so a pre-approved response does not exist.
  When the model call fails this path fails explicitly (ADR-0005). Assembling copy from
  rules instead is exactly how claims the input never made get published.
- **The stub is comic-blind.** Only the single-ad branch is filled, because the walking
  skeleton's single pass-through path is single-ad; the comic branch exists as structure
  and raises (구현_범위 1절). Faking six panels would make the comic path look finished.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from ai_engine import budget, draft_prompt, guardrail, render_prompt, usage
from ai_engine.config import MODEL_MAX_RETRIES, Settings
from ai_engine.models import (
    PANEL_ROLES,
    Brief,
    ComicDraft,
    Draft,
    DraftGenerateRequest,
    DraftGenerateResponse,
    DraftPatchEngineRequest,
    Panel,
    RefusalReason,
    SingleAdDraft,
)

logger = logging.getLogger(__name__)


class DraftFailedError(RuntimeError):
    """시안을 만들지 못했습니다. 라우트가 503 `UPSTREAM_UNAVAILABLE` 로 바꿉니다.

    ⚠️ **거절과 다릅니다.** 거절은 `draft` 를 빼고 `refusalReason` 을 실은 **200** 이며, 쓸 수
    있었는데 지어내지 않고 물러선 상태입니다. 이것은 "지금 이 서비스로는 안 된다" 이고 호출자에게
    폴백이 없습니다 - 카피는 제품마다 달라 사전 승인된 응답이 성립하지 않습니다 (ADR-0005).

    ⚠️ 이 예외를 잡아 규칙 기반으로 카피를 조립하는 코드를 쓰지 마세요. 그것이 곧 입력에 없는
    주장을 내보내는 경로입니다 (생성_파이프라인 3절).
    """


def generate_draft(request: DraftGenerateRequest, settings: Settings) -> DraftGenerateResponse:
    """Write the draft, or refuse.

    A refusal is `draft` omitted with `refusalReason` set — a normal 200, meaning we could
    have written something and declined to invent it.

    `guardrailApplied` is echoed on every response, refusal or not: without it a control run
    and a verified output are indistinguishable and the suppression rate cannot be computed.
    """
    logger.info(
        "draft:generate mode=%s outputType=%s guardrail=%s",
        settings.generation_mode,
        request.output_type,
        request.guardrail_applied,
    )
    if settings.generation_mode == "stub":
        return _generate_stub(request, settings)
    return _generate_with_model(request, settings)


def _generate_stub(request: DraftGenerateRequest, settings: Settings) -> DraftGenerateResponse:
    """Fixed single-ad draft, visibly marked.

    ⚠️ The copy is built **only** from `sellingPoint`, part of the guardrail's evidence
    (`sellingPoint` + `note` + product name, see `_evidence`). Even a stub must not put a
    number or a claim on the wire that the input did not carry — the skeleton is where that
    habit is set.
    """
    if request.output_type == "comic":
        raise NotImplementedError(
            "comic output is a structural branch only in the walking skeleton "
            "(구현_범위 1절); the stub fills the single-ad path"
        )

    marker = settings.stub_marker
    brief = request.brief
    return DraftGenerateResponse(
        draft=SingleAdDraft(
            ad_plan=f"[{marker}] {brief.product_name} 광고 기획안. 근거: {brief.selling_point}",
            ad_copy=f"[{marker}] {brief.selling_point}",
            visual_plan=f"[{marker}] {brief.art_style} 화풍의 제품 단독 컷",
        ),
        guardrail_applied=request.guardrail_applied,
    )


def _generate_with_model(
    request: DraftGenerateRequest, settings: Settings
) -> DraftGenerateResponse:
    """The real generation, through the vendor's text model (기획서 13.2).

    ⚠️ Raise rather than fall back. This seam has no degraded mode by design (ADR-0005).

    ⚠️ **만화형도 여기서는 갈래가 아니라 갈라진 길입니다.** 스텁이 만화형을 거절하는 것은
    여섯 칸을 지어내면 만화 경로가 완성된 것처럼 보이기 때문인데 (구현_범위 1절), 실물 분기가
    실제로 여섯 칸을 쓰는 것은 지어내는 일이 아닙니다. 칸 수와 역할은 계약과 기획서 7.3 이
    정해 두었으므로 여기서 새로 정하는 값이 없습니다.
    """
    build = _comic_draft if request.output_type == "comic" else _single_ad_draft
    outcome = _guarded_draft(
        draft_prompt.build_generate(request),
        settings,
        build,
        _evidence(request.brief),
        enabled=request.guardrail_applied,
        seam="draft:generate",
    )
    return _response(outcome, request.guardrail_applied)


def patch_draft(request: DraftPatchEngineRequest, settings: Settings) -> DraftGenerateResponse:
    """Rewrite the named parts of an existing draft, and nothing else.

    ⚠️ **The fields outside the patch come back unchanged.** That is the whole difference
    between 부분 교체 and regeneration: a caller that asked to change the copy has a visual
    plan it already approved, and quietly rewriting it discards a decision the user made.
    """
    logger.info(
        "draft:patch mode=%s outputType=%s fields=%s guardrail=%s",
        settings.generation_mode,
        request.output_type,
        sorted(request.patch.model_fields_set),
        request.guardrail_applied,
    )
    if settings.generation_mode == "stub":
        return _patch_stub(request, settings)
    return _patch_with_model(request, settings)


def _patch_stub(request: DraftPatchEngineRequest, settings: Settings) -> DraftGenerateResponse:
    """Apply the patch literally, with the stub marker on what moved.

    ⚠️ **The stub takes the caller's text as given** rather than writing new copy from the
    brief. A patch carries what the user typed, and the one thing this branch can honestly
    do with it is put it where it belongs — inventing replacement copy here would put claims
    on the wire that neither the input nor the user supplied (ADR-0005, INV-6).

    ⚠️ Comic-blind, like `_generate_stub`. The skeleton's pass-through path is single-ad and
    the comic branch exists as structure only (구현_범위 1절); patching six panels here would
    make the comic path look finished.
    """
    if request.output_type == "comic":
        raise NotImplementedError(
            "comic output is a structural branch only in the walking skeleton "
            "(구현_범위 1절); the stub patches the single-ad path"
        )

    marker = settings.stub_marker
    # `exclude_unset` and not `exclude_none`: in this family an omitted key and `""` are
    # opposite instructions — "leave it alone" against "empty it" (models/patch.py).
    # ⚠️ `exclude={"panels"}` is now unreachable — `check_patch_matches_output_type` rejects
    # a single-ad patch that names `panels`. Kept because `model_copy` below does not
    # validate: were the check ever removed, this is what stops a stray key from landing on
    # the draft as an attribute. It must never be the thing deciding the outcome, which is
    # exactly what it was doing before 2026-08-18 (silent 200, draft unchanged).
    changes = {
        name: f"[{marker}] {value}"
        for name, value in request.patch.model_dump(exclude_unset=True, exclude={"panels"}).items()
    }
    return DraftGenerateResponse(
        draft=request.draft.model_copy(update=changes),
        guardrail_applied=request.guardrail_applied,
    )


def _patch_with_model(
    request: DraftPatchEngineRequest, settings: Settings
) -> DraftGenerateResponse:
    """The real partial regeneration, through the vendor's text model.

    ⚠️ Raise rather than fall back, for the same reason as `_generate_with_model`: there is
    no pre-approved copy for a product we have not seen.

    ⚠️ **응답으로 시안을 만들지 않고 원문을 복사해 지정된 자리만 덮어씁니다.** 모델이 손대지
    말라고 한 필드까지 돌려주더라도 그것은 읽히지 않습니다 - 부분 교체와 전체 재생성의 차이가
    바로 이것이고 (생성_파이프라인 3절), 사용자가 이미 승인한 문장을 조용히 바꾸는 것은
    응답 모양이 같아서 눈에 띄지도 않습니다.

    ⚠️ 거절도 `draft` 를 뺀 200 입니다. 원문 유지는 **호출자가** 합니다 - 원문을 되돌려
    보내면서 `refusalReason` 을 함께 실으면 계약이 말하는 거절(`draft` 키가 없는 상태)이
    아니게 됩니다.
    """
    original = request.draft

    def build(payload: dict[str, Any]) -> Draft:
        if isinstance(original, ComicDraft):
            return _patched_comic(request, original, payload)
        return _patched_single_ad(request, original, payload)

    outcome = _guarded_draft(
        draft_prompt.build_patch(request),
        settings,
        build,
        _evidence(request.brief),
        enabled=request.guardrail_applied,
        seam="draft:patch",
    )
    return _response(outcome, request.guardrail_applied)


# ---- 가드레일 (ADR-0019, 생성_파이프라인 5.1절) ------------------------------------------


def _evidence(brief: Brief) -> str:
    """가드레일이 대조할 원문. `sellingPoint` + `note` + **제품명**입니다.

    셋 다 근거입니다 (생성_파이프라인 5.2절, 2026-08-20 갱신). `category` 와 `target` 은
    추론값이라 들어가지 않습니다 - 추론으로 채운 카테고리를 근거 삼아 효능을 쓰면 지어낸
    것입니다.

    ⚠️ **제품명은 근거를 넓히려고 넣은 것이 아닙니다.** 사용자가 직접 친 글자를 우리가 지어낸
    것으로 세지 않기 위해서입니다 - 제품명이 "3겹 물티슈" 인데 카피가 `3겹` 이라고 쓰면 그
    수치는 우리가 만든 것이 아닙니다. 제품명은 효능을 실어 올 수 없으므로 근거의 성격은
    그대로입니다.
    """
    parts = (brief.selling_point, brief.note, brief.product_name)
    return " ".join(part for part in parts if part)


def _guarded_draft(
    prompt: str,
    settings: Settings,
    build: Callable[[dict[str, Any]], Draft],
    evidence: str,
    *,
    enabled: bool,
    seam: str,
) -> Draft | RefusalReason:
    """한 번 쓰게 하고, 위반이면 **한 번만** 다시 쓰게 하고, 그래도 남으면 거절합니다.

    생성_파이프라인 5.1.1절의 표 그대로입니다. 1회차 위반은 조용히 재생성하므로 호출자에게
    보이지 않고, 2회차 위반이 `refusalReason: guardrail` 입니다.

    ⚠️ **재생성을 열어 두지 마세요.** 거절이 반복될 때 비용이 무한히 늘고, 그 비용은 사용자가
    기다리는 시간이기도 합니다.

    ⚠️ 검사 대상은 `render_prompt.dialogue_of` 가 주는 문자열 - **이미지 안에 그려질 글자**
    뿐입니다. `adPlan` 과 `visualPlan` 은 소비자에게 하는 주장이 아니라 제작 지시문이라
    넣으면 전량 위반으로 잡힙니다 (2026-08-20 실측, ADR-0019).

    ⚠️ **예산은 여기서 한 번만 잽니다.** 두 시도가 한 예산을 나눠 쓰는 이유는
    `_guarded_attempts` 에 있습니다.
    """
    try:
        return budget.run_within(
            settings.draft_model_timeout_s,
            lambda: _guarded_attempts(
                prompt, settings, build, evidence, enabled=enabled, seam=seam
            ),
        )
    except budget.BudgetExceededError as exc:
        raise DraftFailedError(
            f"{settings.draft_model_timeout_s:.0f}초 예산 안에 오지 않았습니다. "
            "호출자가 먼저 끊기 전에 포기합니다."
        ) from exc


def _guarded_attempts(
    prompt: str,
    settings: Settings,
    build: Callable[[dict[str, Any]], Draft],
    evidence: str,
    *,
    enabled: bool,
    seam: str,
) -> Draft | RefusalReason:
    """`_guarded_draft` 의 본체. 예산 밖에 두는 것은 감쌈 하나뿐입니다.

    ⚠️ **예산이 두 시도를 함께 덮습니다** (이슈 #180 리뷰). 시도마다 새로 시작하면 요청 하나가
    최악 100초인데 호출자(`ADGEN_DRAFT_TIMEOUT_S`)는 60초입니다 - SDK 재시도를 껐어도 풀리지
    않습니다. **우리 자신의 재생성이 두 번째 시도이기 때문**이고, 이것은 예외 경로가 아니라
    D2 대조 실험의 on 팔입니다.

    ⚠️ 그래서 1회차가 느리면 재생성이 쓸 시간이 그만큼 줄고, 남지 않으면 재생성이 예산에서
    끊깁니다. 시도당 상한을 낮추는 방법도 있었지만 그 값을 정할 실측이 없습니다 - 텍스트 모델은
    어느 모델인지를 잰 회차 자체가 없습니다 (`config.text_model`). 호출자가 60초만 기다린다는
    사실은 이미 정해져 있으므로, 나눠 쓰는 쪽이 없는 숫자를 만드는 것보다 낫습니다.
    """
    outcome = _attempt(prompt, settings, build, seam)
    if isinstance(outcome, str) or not enabled:
        return outcome

    report = guardrail.check_claims(render_prompt.dialogue_of(outcome), evidence)
    if report.passed:
        return outcome

    # 1회차 위반. 클라이언트에는 보이지 않습니다 (생성_파이프라인 5.1.1절).
    logger.info("guardrail 1회차 위반, 재생성합니다: %s", report.violations)
    retried = _attempt(
        f"{prompt}\n\n{draft_prompt.retry_block(report.violations)}",
        settings,
        build,
        f"{seam}:retry",
    )
    if isinstance(retried, str):
        return retried

    second = guardrail.check_claims(render_prompt.dialogue_of(retried), evidence)
    if second.passed:
        return retried

    logger.warning("guardrail 2회차 위반, 거절합니다: %s", second.violations)
    return "guardrail"


def _attempt(
    prompt: str, settings: Settings, build: Callable[[dict[str, Any]], Draft], seam: str
) -> Draft | RefusalReason:
    """한 번 물어보고, 거절 사유이거나 시안입니다.

    `seam` 은 사용량 로그의 꼬리표로만 씁니다. 재생성은 `...:retry` 로 따로 세는데,
    **재생성이 예산에서 차지하는 몫이 D2 대조 실험의 판단 축**이기 때문입니다 - 위반율이
    높으면 on 팔의 비용이 off 팔의 두 배로 갑니다.
    """
    payload = _ask_model(prompt, settings, seam)
    reason = _refusal_of(payload)
    return reason if reason is not None else build(payload)


def _response(outcome: Draft | RefusalReason, guardrail_applied: bool) -> DraftGenerateResponse:
    """⚠️ 거절이면 `draft` 를 **넘기지 않습니다.** `None` 을 넘기면 계약이 금지한 `null` 이
    되고, 키를 실으면 "거절인데 시안이 있는" 상태가 됩니다 (계약 `DraftGenerateResponse`)."""
    if isinstance(outcome, str):
        return DraftGenerateResponse(guardrail_applied=guardrail_applied, refusal_reason=outcome)
    return DraftGenerateResponse(draft=outcome, guardrail_applied=guardrail_applied)


# ---- 모델 호출과 응답 해석 ------------------------------------------------------------


def _ask_model(prompt: str, settings: Settings, seam: str) -> dict[str, Any]:
    """프롬프트 하나를 보내고 JSON 하나를 받습니다.

    ⚠️ 두 이음매가 같은 함수를 쓰는 것은 **같은 모듈 안의 두 갈래**이기 때문입니다. 앱 전체가
    쓰는 공용 클라이언트 헬퍼를 만들지는 않습니다 - `render` 도 자기 호출을 자기 안에 두고
    있고, 한 곳으로 모으면 이미지와 텍스트의 실패 처리가 서로를 끌고 다니게 됩니다.

    ⚠️ `temperature` 도 최대 토큰도 보내지 않습니다. 모델마다 허용 범위가 다르고, 지정한
    값이 거절되면 400 하나로 전체 경로가 죽습니다. 재현성이 필요한 자리는 실험 하네스이지
    운영 경로가 아닙니다.
    """
    if not settings.model_api_key:
        raise DraftFailedError(
            "ADGEN_MODEL_API_KEY 가 비어 있습니다. 키 없이 카피를 쓸 수는 없고, "
            "스텁으로 되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절)."
        )

    logger.info("draft prompt=%s model=%s", draft_prompt.VERSION, settings.text_model)

    # ⚠️ 지연 import. `openai` 는 optional extra 라 스텁만 돌리는 CI 와 컨테이너에는 없습니다.
    # 모듈 최상단에서 import 하면 이 파일을 읽는 것만으로 ImportError 가 나고, 증상은
    # "스텁 모드인데 엔진이 기동하지 않는다" 로 보입니다 (`render` 와 같은 이유, 같은 모양).
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈리는 경로
        raise DraftFailedError(
            "openai 패키지가 없습니다. pip install -e './apps/ai-engine[model]' 로 설치하세요."
        ) from exc

    # ⚠️ `max_retries` 를 넘기지 않으면 SDK 기본값 2 가 붙어 50초가 **시도당** 상한이 되고,
    # 최악 150초가 호출자의 60초를 넘깁니다 (이슈 #180). 이쪽은 열화가 없어 실패가 실패로
    # 보이지만, 실패의 이유를 아는 쪽이 아무도 없게 됩니다.
    client = OpenAI(
        api_key=settings.model_api_key,
        timeout=settings.draft_model_timeout_s,
        max_retries=MODEL_MAX_RETRIES,
    )
    try:
        response = client.chat.completions.create(
            model=settings.text_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            n=1,
        )
    except Exception as exc:
        # 벤더 예외 계층에 의존하지 않습니다. 인증 실패도 쿼터 초과도 타임아웃도 호출자에게는
        # 같은 답입니다: 쓸 수 없음 (`render._render_with_model` 의 같은 판단).
        raise DraftFailedError(f"{type(exc).__name__}: {exc}") from exc

    # ⚠️ 본문을 꺼내기 **전에** 기록합니다. `_content` 는 빈 응답에서 예외를 던지는데, 그 호출도
    # 토큰을 쓴 호출이고 요금이 나갑니다. 실패한 회차만 예산에서 빠지면 집계가 실제보다 싸게
    # 보입니다 - 거절과 잘림이 잦은 구간일수록 더 그렇습니다.
    usage.log_usage(logger, seam, settings.text_model, response)

    return _decode(_content(response))


def _content(response: Any) -> str:
    """응답에서 본문을 꺼냅니다.

    ⚠️ **응답의 모양을 신뢰하지 않습니다.** 벤더가 돌려준 객체라 `choices` 가 비었거나 아예
    없거나 `content` 가 `None` 일 수 있습니다. 그대로 두면 `IndexError` 와 `TypeError` 가
    라우트의 503 매핑을 지나쳐 **500 으로 나갑니다** - 계약이 이 경로에 준 실패 코드는 503
    하나인데도 말입니다 (`render._inline_bytes` 가 같은 사고로 고쳐졌습니다, 2026-08-18).
    """
    choices = getattr(response, "choices", None)
    if not choices:
        raise DraftFailedError("응답에 choices 가 없습니다.")
    content = getattr(getattr(choices[0], "message", None), "content", None)
    if not content or not isinstance(content, str):
        raise DraftFailedError("응답 본문이 비어 있습니다 (거절이거나 중간에 끊겼습니다).")
    return content


def _decode(body: str) -> dict[str, Any]:
    """JSON 하나를 읽습니다. 못 읽으면 실패이고, 되살리려 들지 않습니다.

    ⚠️ 깨진 JSON 에서 정규식으로 문장을 건져 내는 코드를 쓰지 마세요. 그렇게 얻은 문자열은
    모델이 쓴 카피가 아니라 우리가 주운 조각이고, 근거 안에 있는지 아무도 확인하지 않았습니다.
    """
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise DraftFailedError(f"응답이 JSON 이 아닙니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise DraftFailedError(f"응답 JSON 이 객체가 아닙니다: {type(payload).__name__}")
    return payload


def _refusal_of(payload: dict[str, Any]) -> RefusalReason | None:
    """거절인지 봅니다. 거절은 **정상 200** 이고 `draft` 가 빠집니다.

    ⚠️ `guardrail` 은 여기서 나올 수 없습니다. 그것은 재생성 1회 뒤에도 근거 밖 주장이 남은
    경우이고 (생성_파이프라인 5.1.1절), 그 판정은 `_guarded_draft` 가
    `ai_engine.guardrail.check_claims` 로 내립니다. 모델이 스스로 `"guardrail"` 이라고 말해도
    그것은 검증을 거친 판정이 아니므로 받아들이지 않습니다.
    """
    refusal = payload.get("refusal")
    if refusal is None:
        return None
    if refusal != "no_evidence":
        raise DraftFailedError(f"알 수 없는 거절 사유입니다: {refusal!r}")
    return "no_evidence"


def _single_ad_draft(payload: dict[str, Any]) -> SingleAdDraft:
    """단일 광고형 시안. 계약 모델로 검증합니다.

    ⚠️ 필드 목록을 여기 다시 적지 않고 `model_validate` 에 맡깁니다. 손으로 꺼내면 계약의
    필드 목록이 두 곳에 생기고, 모르는 키가 조용히 버려집니다 - `Base` 의 `extra="forbid"` 가
    그것을 거절하라고 있는 설정입니다.
    """
    try:
        return SingleAdDraft.model_validate(payload)
    except ValueError as exc:
        raise DraftFailedError(f"단일 광고형 시안 형식이 아닙니다: {exc}") from exc


def _comic_draft(payload: dict[str, Any]) -> ComicDraft:
    """만화형 시안. 칸 번호와 역할은 **우리가** 붙입니다.

    ⚠️ 모델이 보낸 `index` 와 `role` 은 읽지 않습니다 (INV-5). 칸 번호는 배열 순서이고 역할은
    번호가 정합니다 - 모델에게 물으면 여섯 박자가 기획 근거가 아니라 회차마다 흔들리는 값이
    됩니다. 칸이 6개가 아니면 `ComicDraft` 가 거절합니다 (INV-1).
    """
    cells = payload.get("panels")
    if not isinstance(cells, list):
        raise DraftFailedError(f"panels 가 배열이 아닙니다: {type(cells).__name__}")
    if len(cells) != len(PANEL_ROLES):
        raise DraftFailedError(f"칸이 {len(cells)}개입니다. 6개 고정입니다 (INV-1).")

    panels = []
    for index, (cell, role) in enumerate(zip(cells, PANEL_ROLES, strict=True), start=1):
        if not isinstance(cell, dict):
            raise DraftFailedError(f"{index}번 칸이 객체가 아닙니다.")
        try:
            panels.append(
                Panel(index=index, role=role, scene=cell["scene"], dialogue=cell["dialogue"])
            )
        except (KeyError, ValueError) as exc:
            raise DraftFailedError(f"{index}번 칸 형식이 아닙니다: {exc}") from exc

    try:
        return ComicDraft(ad_plan=_text_at(payload, "adPlan"), panels=panels)
    except ValueError as exc:
        raise DraftFailedError(f"만화형 시안 형식이 아닙니다: {exc}") from exc


def _patched_single_ad(
    request: DraftPatchEngineRequest, draft: SingleAdDraft, payload: dict[str, Any]
) -> SingleAdDraft:
    """지정된 필드만 덮어쓴 사본.

    ⚠️ `model_copy(update=...)` 는 검증하지 않으므로 값이 문자열인지 여기서 봅니다. 숫자나
    객체가 그대로 들어가면 시안은 만들어지고 계약 위반은 직렬화 시점에야 - 혹은 영영 -
    드러납니다.
    """
    changes: dict[str, str] = {}
    if "ad_copy" in request.patch.model_fields_set:
        changes["ad_copy"] = _text_at(payload, "copy")
    if "visual_plan" in request.patch.model_fields_set:
        changes["visual_plan"] = _text_at(payload, "visualPlan")
    return draft.model_copy(update=changes)


def _patched_comic(
    request: DraftPatchEngineRequest, draft: ComicDraft, payload: dict[str, Any]
) -> ComicDraft:
    """지정된 칸의 지정된 부분만 덮어쓴 사본.

    ⚠️ 패치에 없는 칸은 손대지 않고, 패치에 있는 칸이라도 이름 없는 부분은 그대로 둡니다.
    대사만 바꿔 달라고 한 요청이 장면까지 바꿔 놓으면 사용자가 승인한 결정이 사라집니다.
    """
    if request.patch.panels is None:
        raise DraftFailedError("만화형 패치인데 panels 가 없습니다.")

    cells = payload.get("panels")
    if not isinstance(cells, dict):
        raise DraftFailedError(f"panels 가 객체가 아닙니다: {type(cells).__name__}")

    panels = list(draft.panels)
    for key, cell_patch in request.patch.panels.root.items():
        answer = cells.get(key)
        if not isinstance(answer, dict):
            raise DraftFailedError(f"{key}번 칸의 응답이 없습니다.")
        # ⚠️ `dict[str, str]` 을 명시합니다. 튜플 리터럴을 도는 컴프리헨션은 키를
        # `Literal["scene", "dialogue"]` 로 추론하는데, `Mapping` 은 키에 불변이라
        # `model_copy(update=...)` 가 그 타입을 받지 않습니다.
        changes: dict[str, str] = {
            name: _text_at(answer, name)
            for name in ("scene", "dialogue")
            if name in cell_patch.model_fields_set
        }
        position = int(key) - 1
        panels[position] = panels[position].model_copy(update=changes)

    return draft.model_copy(update={"panels": panels})


def _text_at(payload: dict[str, Any], key: str) -> str:
    """문자열 하나를 꺼냅니다. 없거나 문자열이 아니면 실패입니다.

    ⚠️ 빈 문자열은 통과시킵니다. 이 계열에서 `""` 는 "비어 있음" 이라는 정상 값이고, 패치가
    비우라고 지시할 수 있는 자리입니다 (계약 3절).
    """
    value = payload.get(key)
    if not isinstance(value, str):
        raise DraftFailedError(f"{key} 가 문자열이 아닙니다: {type(value).__name__}")
    return value

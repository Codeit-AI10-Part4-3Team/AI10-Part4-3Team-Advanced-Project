"""모델 호출이 실제로 쓴 토큰을 로그로 남깁니다.

⚠️ **이것이 없으면 예산을 사후에 재구성할 수 없습니다.** 2026-08-20 까지 두 텍스트 이음매는
`response.usage` 를 받아서 그대로 버렸고, 그래서 "가드레일 실험에 얼마를 썼는가" 에 답할 수
있는 기록이 어디에도 없었습니다. 프롬프트 토큰은 빌더를 다시 돌려 셀 수 있지만 **추론 토큰은
호출한 그 순간에만 알 수 있습니다** - gpt-5 는 추론 토큰도 출력 단가로 과금하는데, 짧은 JSON
하나를 뽑는 호출에서도 그 수가 회차마다 다릅니다.

⚠️ **여기에 단가(USD)를 넣지 마세요.** 벤더가 값을 바꾸면 코드에 박힌 상수는 조용히 거짓말이
되고, 그 숫자가 보고서로 들어갑니다. 이 모듈이 남기는 것은 토큰 수뿐이고, USD 환산은 그때의
가격표를 함께 적는 실험 하네스의 몫입니다.

⚠️ **실패해도 호출을 죽이지 않습니다.** 사용량 기록은 부가 정보이고, 여기서 예외가 나가면
이미 성공한 생성이 503 으로 바뀝니다.
"""

import logging
from typing import Any

PREFIX = "usage"
"""로그 줄의 첫 낱말. 집계 스크립트가 이 접두어로 골라냅니다 - 형식을 바꾸면 과거 로그와
지금 로그를 한 번에 못 셉니다."""


def log_usage(logger: logging.Logger, seam: str, model: str, response: Any) -> None:
    """한 번의 호출이 쓴 토큰을 `key=value` 로 남깁니다.

    `seam` 은 어느 이음매인지(`draft:generate`, `brief:fill` 등)입니다. 회차별 비용이 이음매
    마다 다르므로, 이 값 없이 총량만 남기면 어디를 줄여야 하는지 알 수 없습니다.

    ⚠️ **응답의 모양을 신뢰하지 않습니다** (`draft._content` 와 같은 이유). `usage` 가 없거나
    필드가 비는 경우가 실제로 있고, 그때는 없다고 적습니다 - 0 으로 적으면 "안 썼다" 와
    "모른다" 가 로그에서 구별되지 않습니다.
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            logger.info("%s seam=%s model=%s unavailable", PREFIX, seam, model)
            return

        prompt = _field(usage, "prompt_tokens")
        completion = _field(usage, "completion_tokens")
        total = _field(usage, "total_tokens")
        cached = _field(getattr(usage, "prompt_tokens_details", None), "cached_tokens")
        reasoning = _field(getattr(usage, "completion_tokens_details", None), "reasoning_tokens")

        logger.info(
            "%s seam=%s model=%s prompt=%s cached=%s completion=%s reasoning=%s total=%s",
            PREFIX,
            seam,
            model,
            prompt,
            cached,
            completion,
            reasoning,
            total,
        )
    except Exception:  # pragma: no cover - 기록 실패가 생성을 죽이지 않게 하는 마지막 그물
        logger.warning("%s seam=%s 기록 실패", PREFIX, seam, exc_info=True)


def _field(holder: Any, name: str) -> str:
    """숫자면 그대로, 아니면 `?`. **0 과 구별됩니다** (위 docstring 참고)."""
    value = getattr(holder, name, None)
    return str(value) if isinstance(value, int) else "?"

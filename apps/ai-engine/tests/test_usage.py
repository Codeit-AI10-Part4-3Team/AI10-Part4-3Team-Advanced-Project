"""사용량 기록. 예산을 사후에 재구성할 수 있게 하는 것이 이 모듈의 존재 이유입니다.

⚠️ 여기서 지키는 성질은 두 가지입니다. **모르는 것을 0 으로 적지 않는다**, 그리고
**기록이 실패해도 생성을 죽이지 않는다.** 앞의 것을 어기면 집계가 실제보다 싸게 나오고,
뒤의 것을 어기면 부가 정보 때문에 이미 성공한 호출이 503 이 됩니다.
"""

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from ai_engine import usage


def response_with(**fields: Any) -> SimpleNamespace:
    """벤더 응답 흉내. `usage` 객체 하나만 있으면 됩니다."""
    return SimpleNamespace(usage=SimpleNamespace(**fields))


def test_every_field_lands_in_one_line(caplog: pytest.LogCaptureFixture) -> None:
    """집계 스크립트가 한 줄만 읽어도 회차 하나의 비용을 계산할 수 있어야 합니다."""
    logger = logging.getLogger("test.usage.full")
    response = response_with(
        prompt_tokens=437,
        completion_tokens=612,
        total_tokens=1049,
        prompt_tokens_details=SimpleNamespace(cached_tokens=128),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=512),
    )

    with caplog.at_level(logging.INFO, logger="test.usage.full"):
        usage.log_usage(logger, "draft:generate", "gpt-5", response)

    line = caplog.messages[0]
    assert line.startswith("usage ")
    for fragment in (
        "seam=draft:generate",
        "model=gpt-5",
        "prompt=437",
        "cached=128",
        "completion=612",
        "reasoning=512",
        "total=1049",
    ):
        assert fragment in line


def test_a_missing_usage_says_so_instead_of_logging_zeros(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """⚠️ 0 으로 적으면 "안 썼다" 와 "모른다" 가 로그에서 구별되지 않습니다. 그 상태로 집계하면
    사용량이 실제보다 작게 나오고, 그 숫자로 회차 수를 늘리는 판단을 하게 됩니다."""
    logger = logging.getLogger("test.usage.none")

    with caplog.at_level(logging.INFO, logger="test.usage.none"):
        usage.log_usage(logger, "brief:fill", "gpt-5", SimpleNamespace())

    assert "unavailable" in caplog.messages[0]
    assert "prompt=0" not in caplog.messages[0]


def test_reasoning_tokens_are_unknown_not_zero_when_absent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """추론 토큰은 벤더가 늘 채워 주는 값이 아닙니다. 없을 때 0 으로 적으면 gpt-5 의 출력
    비용을 통째로 빠뜨립니다 - 추론 토큰도 출력 단가로 과금되기 때문입니다."""
    logger = logging.getLogger("test.usage.partial")
    response = response_with(prompt_tokens=437, completion_tokens=70, total_tokens=507)

    with caplog.at_level(logging.INFO, logger="test.usage.partial"):
        usage.log_usage(logger, "draft:generate", "gpt-5", response)

    assert "reasoning=?" in caplog.messages[0]
    assert "cached=?" in caplog.messages[0]
    assert "prompt=437" in caplog.messages[0]


def test_a_hostile_response_does_not_kill_the_call(caplog: pytest.LogCaptureFixture) -> None:
    """⚠️ 기록은 부가 정보입니다. 여기서 예외가 나가면 이미 성공한 생성이 503 이 됩니다."""

    class Exploding:
        @property
        def usage(self) -> Any:
            raise RuntimeError("벤더 객체가 접근에서 터집니다")

    logger = logging.getLogger("test.usage.hostile")

    with caplog.at_level(logging.WARNING, logger="test.usage.hostile"):
        usage.log_usage(logger, "draft:patch", "gpt-5", Exploding())

    assert "기록 실패" in caplog.messages[0]

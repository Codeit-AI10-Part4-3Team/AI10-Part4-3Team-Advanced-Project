"""Runtime settings.

Values come from the environment (infra/.env, never committed). The defaults are the
offline ones so a fresh clone runs without configuration.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

GenerationMode = Literal["stub", "model"]
"""Which side of every generation seam is live.

⚠️ **This is the single switch, and it is deliberately visible.** 구현_범위 1.1절 requires
that the running branch be readable without opening the source, because mistaking a stub
response for a measurement is the failure that quietly invalidates every number we report.
`stub` is the default while the walking skeleton is being assembled; flipping to `model`
turns the not-yet-written branches into explicit failures rather than silent fallbacks.
"""


class Settings(BaseSettings):
    """`ADGEN_` prefix keeps our variables distinguishable from everything else on the host."""

    model_config = SettingsConfigDict(env_prefix="ADGEN_", extra="ignore")

    generation_mode: GenerationMode = "stub"

    # Where the stub places its placeholder marker. Kept configurable so a screenshot in a
    # report can never be mistaken for a real render.
    stub_marker: str = "STUB"

    # ---- 외부 이미지 생성 API (ADR-0003) ------------------------------------------------

    model_api_key: str = ""
    """이미지 생성 API 키.

    ⚠️ **비어 있는 것이 정상 기본값입니다.** 값이 없으면 `generation_mode` 가 `model` 이어도
    호출 자체가 성립하지 않으므로 렌더가 명시적으로 실패합니다 - 키가 없다고 스텁으로
    되돌아가면 그 결과가 측정값처럼 보입니다 (구현_범위 1.1절).

    ⚠️ 이 값은 **ai-engine 에만** 둡니다. backend 는 8000 을 외부에 여는 쪽이고, 유료 키를
    거기 함께 두지 않는 것이 두 앱을 나눈 이유 중 하나입니다 (infra/docker-compose.yml).
    """

    image_model: str = "gpt-image-2"
    """검증 1순위가 실제로 통과시킨 모델입니다 (2026-08-14, RESULTS.md).

    문자열로 두는 이유는 벤더가 모델명을 바꿀 때 코드 변경 없이 따라가기 위해서이고,
    기본값을 실측한 모델로 두는 이유는 **아무도 지정하지 않았을 때 검증된 것이 돌게**
    하기 위해서입니다.
    """

    image_quality: str = ""
    """비우면 API 에 싣지 않습니다.

    ⚠️ 지정하지 않으면 모델이 회차마다 품질 티어를 고릅니다. 같은 조건 10회에서 출력 토큰이
    1674 와 3826 으로 갈렸고 **비용이 2.3배** 차이났습니다 (2026-08-13 실측). 그럼에도
    기본값을 비워 두는 것은 받는 값이 확인되지 않았기 때문입니다 - 잘못된 값을 상수로
    박으면 모든 호출이 400 으로 죽습니다.

    **운영 설정값은 출력 유형별로 갈립니다** (2026-08-18 회의, 생성_파이프라인 6.2절):

    | 출력 유형 | `quality` | 세트당 단가 | 왜 |
    |---|---|---|---|
    | 만화형 | `medium` | 0.4041 USD | `low` 에서 손 표현과 물리가 무너지는 결함이 관측됨 |
    | 단일 광고형 | `low` | 0.0069 USD | 같은 결함이 확인되지 않음 |

    ⚠️ **이 항목이 단일 값이라 유형별로 다르게 줄 수 없습니다.** 위 표를 실제로 적용하려면
    설정을 유형별로 쪼개거나 요청이 티어를 실어 보내야 하며, 그 결정은 아직 열려 있습니다
    (미결정_대장 E-2). 그때까지 운영에서는 만화형 렌더에 맞춰 `medium` 을 넣고, 개발 중에는
    스텁 모드나 `low` 로 돌려 예산을 아끼십시오 - 남은 예산에서 만화형 `medium` 은 약 49세트가
    상한입니다.
    """

    image_timeout_s: float = 300.0
    """한 장에 54 ~ 122초가 걸렸습니다 (2026-08-14 실측). 기다리는 쪽은 사용자가 아니라 잡
    워커이므로 분 단위가 허용됩니다 (ADR-0015, API_계약 2.1절)."""


def get_settings() -> Settings:
    """Read settings. Callers cache — see `ai_engine.service`, which holds the instance."""
    return Settings()

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

    image_quality_override: str = ""
    """개발용 강제 override. **비어 있는 것이 정상이고, 그때 티어는 요청이 정합니다.**

    ⚠️ **이것은 운영 설정값이 아닙니다.** 품질 티어는 2026-08-20 부터 `ImageRenderRequest.quality`
    로 들어옵니다 (미결정_대장 E-2). 호출자가 출력 유형을 보고 정하며, 값의 정본은 backend 의
    `COMIC_QUALITY` / `SINGLE_AD_QUALITY` 상수입니다:

    | 출력 유형 | `quality` | 세트당 단가 | 왜 |
    |---|---|---|---|
    | 만화형 | `medium` | 0.4041 USD | `low` 에서 손 표현과 물리가 무너지는 결함이 관측됨 |
    | 단일 광고형 | `low` | 0.0069 USD | 같은 결함이 확인되지 않음 |

    **그런데도 이 항목이 있는 이유는 돈입니다.** 개발과 검증 실험은 `low` 로 돌려야 하는데
    (생성_파이프라인 6.2절), 그러자고 backend 의 운영 상수를 고치면 그 값이 그대로 배포됩니다.
    엔진 쪽에 끄고 켤 수 있는 지점을 하나 두는 편이 안전합니다 - 남은 예산에서 만화형 `medium`
    은 약 49세트가 상한입니다.

    ⚠️ **채우면 요청에 실려 온 티어를 덮어씁니다.** 그래서 발동할 때마다 경고 로그를 남깁니다.
    이것이 켜진 채로 잰 숫자는 운영 경로의 숫자가 아닙니다.

    이름이 `ADGEN_IMAGE_QUALITY` 에서 바뀐 것은 의도적입니다. 옛 이름은 "운영 설정값" 으로
    읽혔고, 실제로 그렇게 쓰이던 자리를 계약이 가져갔습니다.
    """

    image_timeout_s: float = 120.0
    """**칸 하나**를 기다리는 상한입니다. 응답 전체가 아닙니다.

    ⚠️ **300 에서 내린 값입니다** (2026-08-20, 이슈 #141). 만화형이 칸별 생성으로 바뀌면서
    한 번의 렌더가 호출 6회가 됐고, 300 이면 최악 대기가 `1번 칸 300 + 병렬 300 = 600초` 입니다.
    호출자는 `render_timeout_s`(300초)에 포기하므로 **요금은 나가고 렌더 1회(INV-3)도 소진된
    채 실패로** 뜹니다. 평상시에는 드러나지 않습니다 - 드러나는 날은 벤더가 느려진 날이고,
    그날 증상은 "렌더가 실패한다"가 아니라 "돈은 나갔는데 실패로 뜬다"입니다.

    120 인 근거는 실측입니다. `medium` 병렬 한 세트가 전 구간 118.0초였고(2026-08-20,
    `POST /v1/image:render`), 그 값은 1번 칸과 가장 느린 병렬 칸의 **합**이므로 어느 단계도
    118.0초를 넘지 않았습니다. 즉 120 은 관측된 두 단계 각각의 위에 있습니다.

    ⚠️ `high` 티어는 재지 않았습니다. 동시 호출에서 개별 호출이 팽창하는 비율이 티어가 무거울수록
    커지므로(`low` 44%, `medium` 64%), `high` 를 채택하면 이 값을 다시 재야 합니다.
    """

    render_budget_s: float = 240.0
    """**응답 전체**의 상한. 만화형은 두 단계라 칸당 상한만으로는 총합이 잡히지 않습니다.

    1번 칸 120 + 병렬 배치 120 = 240 이고, 호출자의 `render_timeout_s`(300초)보다 작습니다.
    **핵심은 숫자가 아니라 누가 먼저 실패하는가입니다** (이슈 #141). 두 값이 같으면 어느 쪽이
    먼저 끊길지가 벤더의 그날 속도에 달립니다. 호출자가 먼저 끊으면 실패의 이유를 아는 쪽이
    아무도 없고, 엔진이 먼저 실패하면 어느 칸에서 막혔는지를 남길 수 있습니다.

    ⚠️ 이름이 호출자의 `ADGEN_RENDER_TIMEOUT_S` 와 다른 것은 의도적입니다. 두 앱이 같은
    `ADGEN_` 접두어를 쓰므로 같은 이름을 두면 `infra/.env` 한 줄이 양쪽을 함께 움직이는데,
    두 값은 **같으면 안 됩니다** (`brief_fill_model_timeout_s` 와 같은 사정).
    """

    # ---- 카피 생성 API (기획서 13.2, 2026-08-19 유지 확인) ------------------------------

    text_model: str = "gpt-5"
    """`brief:fill` 과 `draft:*` 가 부르는 텍스트 모델. 사진을 읽는 호출이 섞여 있으므로
    이미지 입력을 받는 모델이어야 합니다 (생성_파이프라인 1절 1단계).

    ⚠️ **`image_model` 과 달리 실측으로 고른 값이 아닙니다.** 그쪽 기본값은 검증 1순위가
    통과시킨 모델이지만, 텍스트 쪽은 "전 구간 GPT API" 라는 경로만 확인됐고
    (2026-08-19 회의록 2번) 어느 모델인지를 잰 회차가 없습니다. 그러니 이 값은 **출발점이지
    근거가 아닙니다** - 여기서 나온 카피 품질 숫자를 보고할 때는 어느 모델로 뽑았는지를 함께
    적으세요.

    ⚠️ 키는 `model_api_key` 를 같이 씁니다. 같은 벤더의 같은 키이고, 둘로 나누면 한쪽만 채운
    배포가 "이미지는 되는데 카피는 안 되는" 상태로 조용히 굴러갑니다.
    """

    brief_fill_model_timeout_s: float = 12.0
    """`brief:fill` 이 벤더를 기다리는 상한. 호출자의 15초보다 **작아야 합니다.**

    ⚠️ 이름이 backend 의 `ADGEN_BRIEF_FILL_TIMEOUT_S` 와 다른 것은 의도적입니다. 두 앱이 같은
    `ADGEN_` 접두어를 쓰므로 같은 이름을 두면 `infra/.env` 한 줄이 양쪽을 함께 움직이는데,
    두 값은 **같으면 안 됩니다** - 호출자 쪽은 "얼마나 기다려 주는가"이고 이쪽은 "그 안에
    포기하는가"입니다. 같아지면 누가 먼저 끊었는지를 로그로 가릴 수 없게 됩니다
    (API_계약 2절, ADR-0005).
    """

    draft_model_timeout_s: float = 50.0
    """`draft:generate` 와 `draft:patch` 의 상한. 호출자의 60초보다 작습니다.

    이름을 backend 의 `ADGEN_DRAFT_TIMEOUT_S` 와 나눈 이유는 위와 같습니다.
    """


def get_settings() -> Settings:
    """Read settings. Callers cache — see `ai_engine.service`, which holds the instance."""
    return Settings()

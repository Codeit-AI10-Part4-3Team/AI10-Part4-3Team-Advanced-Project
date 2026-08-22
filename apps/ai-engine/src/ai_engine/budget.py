"""벽시계 예산 — "엔진이 호출자보다 먼저 포기한다" 를 집행하는 한 자리.

세 이음매 전부가 같은 짝을 씁니다: 엔진 쪽 상한이 호출자 쪽 대기보다 **작아야** 하고, 그래야
실패했을 때 어디서 막혔는지가 우리 로그에 남습니다. 2026-08-21 회의록 04절이 확정한 것은
값(120 / 240 / 300)이 아니라 그 **순서**입니다.

⚠️ **`timeout=` 만으로는 그 순서가 성립하지 않습니다** (이슈 #180). 두 가지 이유가 겹칩니다.

1. **SDK 재시도.** `openai` 는 타임아웃도 재시도하므로 넘기지 않으면 `timeout=` 이 시도당
   상한이 됩니다. 그래서 세 호출 지점 전부가 `config.MODEL_MAX_RETRIES` 를 넘깁니다.
2. **httpx 는 단계별로 잽니다.** 재시도를 껐어도 `timeout=` 은 connect/read/write 를 **각각**
   재는 값이라, 한 번의 시도가 그 값을 넘을 수 있습니다.

1번은 스위치로 닫히지만 2번은 닫히지 않습니다. 그리고 **우리 자신의 재시도**도 있습니다 -
`draft` 의 가드레일 재생성이 그것이고, 스위치와 무관하게 시도가 두 번입니다. 남는 방법은
벽시계를 우리가 직접 재는 것 하나뿐이고, 그 자리가 여기입니다.

⚠️ **기다리기를 그만두는 것이지 호출을 취소하는 것이 아닙니다.** 이미 나간 요청은 벤더 쪽에서
계속 돌고 요금도 나갑니다. 우리가 사는 것은 **호출자가 먼저 끊지 않게 하는 것** 하나뿐입니다.
"""

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor


class BudgetExceededError(TimeoutError):
    """예산 안에 돌아오지 않았습니다.

    ⚠️ **이 예외를 호출자에게 그대로 올리지 마세요.** 이음매마다 실패 타입이 다르고
    (`RenderFailedError` · `BriefFillFailedError` · `DraftFailedError`), 그 타입이 라우트의
    상태 코드와 열화 여부를 정합니다. 여기서는 "예산을 넘겼다" 만 말하고 뜻은 이음매가 붙입니다.
    """


def wait_for[T](future: Future[T], deadline: float) -> T:
    """이미 나간 작업을 데드라인까지만 기다립니다. `deadline` 은 `time.monotonic()` 기준.

    여러 호출이 한 예산을 나눠 쓰는 자리(만화형의 1번 칸과 병렬 배치)를 위해 데드라인을 받습니다 -
    남은 시간을 매번 다시 계산하면 단계마다 예산이 새로 시작됩니다.
    """
    try:
        return future.result(timeout=max(0.0, deadline - time.monotonic()))
    except TimeoutError as exc:
        raise BudgetExceededError from exc


def run_within[T](budget_s: float, call: Callable[[], T]) -> T:
    """`call` 을 워커 스레드에서 부르고 `budget_s` 안에 안 돌아오면 `BudgetExceededError`.

    ⚠️ `with` 를 쓰지 않습니다. `__exit__` 이 `shutdown(wait=True)` 라, 예산을 넘겨 빠져나갈
    때도 붙잡힌 스레드를 끝까지 기다립니다 - 그러면 예산이 아무 일도 하지 않습니다.

    ⚠️ **워커는 데몬이 아닙니다.** 버리고 나와도 `concurrent.futures.thread._python_exit` 가
    인터프리터 종료에서 join 하므로, 붙잡힌 호출이 살아 있는 동안 프로세스 종료가 늘어집니다.
    벤더 쪽 `timeout=` 이 결국 끊어 주므로 무한은 아니고, 상한은 그 값입니다.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return wait_for(pool.submit(call), time.monotonic() + budget_s)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

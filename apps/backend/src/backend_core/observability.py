"""Operational measurements: how long a seam took, and how it ended.

The DoD is "지연 p95, 실패율, `degraded` 비율을 사후 조회 가능" (05 일정 08-26). Three
decisions follow from *사후*, and none of them are about the metrics themselves.

⚠️ **The database cannot answer these.** `jobs` keeps `created_at` and nothing else — no
start, no finish — so latency is not derivable from a row. Adding columns would not help
either: the retention sweep deletes sessions and results after 7 days (세션_보관_정책 2절),
and the log period is 30. A record that outlives its own subject has to live outside it.

⚠️ **Standard output is not a record here.** `deploy-vm.sh` runs `compose up -d --build`,
which *replaces* containers, and the json-file log dies with the container it belonged to.
Every deploy was erasing the history that 세션_보관_정책 2절 promises to keep for 30 days,
which is why this module writes to a file under the `adgen-state` volume (ADR-0014) instead
of trusting the runtime. That policy section already says "회전은 배포 쪽에서 정합니다"; the
deployment had no `logging:` block at all, so nobody was deciding it.

⚠️ **The line format is a contract with the aggregation script**, the same arrangement
`ai_engine.usage` uses and for the same reason: change the shape and past logs stop being
countable next to present ones. Keep `PREFIX` first and everything else `key=value`.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

PREFIX = "obs"
"""First word of every measurement line. The aggregation script selects on it."""

_HANDLER_TAG = "adgen-observability"
"""Marks our handler so installing twice replaces rather than doubles. Tests build a fresh
`Settings` per test; without this the root logger would collect one handler per test and the
last tests would write every line dozens of times."""


def record(
    logger: logging.Logger, seam: str, outcome: str, elapsed_ms: int, **fields: object
) -> None:
    """One completed seam call, as `key=value`.

    `outcome` is what happened, not whether it was an error: `brief:fill` ending in
    `degraded` is a designed outcome (ADR-0005), and counting it as a failure would make the
    failure rate meaningless while hiding the number the report actually wants.

    ⚠️ **Never pass a product photo, a copy string, or a login id.** 세션_보관_정책 2절: the
    log keeps `sessionId`, sizes and formats, nothing else.
    """
    extra = "".join(f" {key}={value}" for key, value in fields.items())
    logger.info("%s seam=%s outcome=%s elapsed_ms=%d%s", PREFIX, seam, outcome, elapsed_ms, extra)


@contextmanager
def measured() -> Iterator[Callable[[], int]]:
    """Yield a callable returning milliseconds elapsed so far.

    ⚠️ `perf_counter`, not `time()`. The wall clock can step backwards (NTP), and a negative
    latency in the p95 input is worse than a missing one — it is not obviously wrong.

    The value is read at `record` time rather than on exit because a seam reports *inside*
    its own branch: the failure path and the success path emit different outcomes, and both
    want the duration up to that point.
    """
    started = time.perf_counter()
    yield lambda: int((time.perf_counter() - started) * 1000)


def install_file_log(log_dir: str | Path, retention_d: int) -> None:
    """Send the root logger to a rotating file as well as to standard output.

    Daily rotation with `backupCount=retention_d` is what makes "30일" a fact rather than an
    intention. Size-based rotation cannot state a period — a busy week would silently hold
    four days and a quiet month would hold ninety.

    ⚠️ `TimedRotatingFileHandler` is not safe across processes: two writers race on the
    rename and one day's file is lost. That is fine **here and only here** because the
    backend runs as a single process — the same property the render queue depends on, and
    for which `apps/backend/Dockerfile` refuses `--workers` (미결정_대장 N19). If that ever
    changes, this rotation breaks too, and it will break quietly.

    Failure to open the file is not fatal. A read-only or full volume must not stop the
    service from serving: losing the measurement is bad, losing the deployment is worse.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_adgen_tag", None) == _HANDLER_TAG:
            root.removeHandler(existing)
            existing.close()

    directory = Path(log_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = TimedRotatingFileHandler(
            directory / "app.log",
            when="midnight",
            backupCount=retention_d,
            encoding="utf-8",
            utc=True,
        )
    except OSError:
        # ⚠️ Returning here leaves the root without our stream handler too, which is correct:
        # if we could not open the file, nothing about stdout has changed yet, so
        # `lastResort` still carries warnings exactly as it did before this function existed.
        logging.getLogger(__name__).warning(
            "운영 로그 파일을 열 수 없습니다: %s. 표준 출력만 남습니다 (배포마다 사라집니다).",
            directory,
            exc_info=True,
        )
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handler._adgen_tag = _HANDLER_TAG  # type: ignore[attr-defined]
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # ⚠️ **Adding the file handler is what makes this one necessary**, and leaving it out was
    # a real defect (PR #181 리뷰). Under the container `CMD` uvicorn's logging config defines
    # no `root` entry, so the root logger has *no* handlers and application warnings reach
    # stderr only through `logging.lastResort` — which Python uses precisely because
    # `callHandlers` found none. The moment a handler exists, `lastResort` is skipped and
    # every `logger.warning` from `backend_core.render`, `api.errors` and `api.worker` would
    # go to the file and nowhere else. `scripts/deploy-vm.sh` dumps `compose logs --tail 40`
    # as its failure diagnostic and the CI smoke prints `docker logs`; both would have gone
    # blind on the exact failures they exist to show, silently.
    stream = logging.StreamHandler(sys.stdout)
    stream._adgen_tag = _HANDLER_TAG  # type: ignore[attr-defined]
    stream.setFormatter(formatter)
    root.addHandler(stream)

    # uvicorn configures the root logger at WARNING; our lines are INFO and would be dropped
    # before reaching any handler. Raising the *root* level rather than the handler's is the
    # part that matters — a handler cannot see what the logger never emits.
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    # ⚠️ Scoped, not global. `httpx` is the transport in `backend_core.ai_client` and logs one
    # INFO line per upstream call; with the root at INFO those would land in a file kept for
    # 30 days with no size cap. The seam records are what this file is for.
    logging.getLogger("httpx").setLevel(logging.WARNING)

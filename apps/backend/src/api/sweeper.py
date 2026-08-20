"""보존 기간 정리 배치의 **when**. `backend_core.retention` owns what gets deleted.

Same split, and the same reasons, as `api.worker` next door: a background task inside the
backend process (ADR-0015), so there is no second deployment artifact and no cron to keep in
step with the compose file. The policy that decides what expires stays testable without a
clock or a server.

⚠️ **It sweeps once at startup, then on a timer.** A daily period inside a process that
restarts on every deploy would otherwise mean the sweep never runs on a day with two
deploys — the interval resets each time. Running immediately makes the schedule "at least
daily" instead of "exactly daily, if nobody deploys", and the sweep is idempotent so an
extra pass costs a table scan.

⚠️ The sweep is blocking (SQLite plus file deletes), so it runs through `anyio.to_thread`
like the render loop. With one worker, doing it on the event loop would stall every request
for the length of the pass.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import timedelta

import anyio

from backend_core import retention, sessions
from backend_core.config import Settings
from backend_core.storage import connect

logger = logging.getLogger(__name__)


def policy_from(settings: Settings) -> retention.Policy:
    """Turn the configured numbers into the periods the policy talks about."""
    return retention.Policy(
        photo=timedelta(hours=settings.retention_photo_h),
        session=timedelta(days=settings.retention_session_d),
    )


def sweep_once(settings: Settings) -> retention.SweepReport:
    """One pass, on whatever thread the caller is on.

    Public so the operator path exists: this is what a manual run calls, and what a test
    calls instead of waiting a day.
    """
    with connect(settings.db_path) as connection:
        return retention.sweep(
            connection,
            settings.image_dir,
            policy_from(settings),
            sessions.now(),
        )


async def run(settings: Settings, interval_s: float) -> None:
    """Sweep until cancelled.

    ⚠️ The loop must outlive any single pass. An unhandled error here would kill the task and
    every later sweep silently never runs — and the symptom is nothing at all, for days,
    until someone notices the disk or the policy being quietly broken. That is exactly the
    failure this batch exists to prevent, so it is caught and the loop continues.
    """
    while True:
        try:
            await anyio.to_thread.run_sync(sweep_once, settings, abandon_on_cancel=True)
        except Exception:
            logger.exception("retention sweep failed; will retry on the next interval")
        await anyio.sleep(interval_s)


@contextlib.asynccontextmanager
async def lifespan_task(settings: Settings) -> AsyncIterator[None]:
    """Run the sweeper for as long as the app is up, when it is turned on.

    ⚠️ `sweep_enabled` defaults to **on** so a deployment cannot forget it. Only the test
    suite turns it off: nearly every test creates a session and asserts on it, and a sweeper
    running underneath with a shortened period could delete the fixture between the request
    and the assertion. Tests that mean to exercise retention call `sweep_once` directly.

    Cancelled on shutdown rather than joined. A pass is short, but waiting on one would still
    add a stall to every deploy for no gain — whatever it did not finish is still expired
    when the next startup sweeps.
    """
    if not settings.sweep_enabled:
        logger.info("retention sweeper disabled by configuration")
        yield
        return

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(run, settings, settings.sweep_interval_s)
        try:
            yield
        finally:
            tasks.cancel_scope.cancel()

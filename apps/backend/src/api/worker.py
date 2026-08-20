"""The render worker's loop, and the recovery it needs at startup.

ADR-0015: one background task inside the backend process. This module owns **when** work
happens; `backend_core.render` owns what happens. The split is what lets a whole render be
tested without starting a server.

⚠️ The loop does not decide whether it may run — `jobs.next_queued` refuses while anything
is `running`. Serial execution is a property of the storage, not of this file, because there
is one GPU and a rule kept in a loop stops being a rule the moment a second loop exists.

⚠️ The render itself is blocking (SQLite and an HTTP call of minutes), so it runs through
`anyio.to_thread`. Calling it directly from this coroutine would park the event loop for the
length of a render, and with a single worker that stalls **every** other request
(API_계약.md 2.2절).
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import AsyncIterator
from datetime import timedelta

import anyio
from fastapi import FastAPI

from api import deps
from backend_core import jobs, render
from backend_core.config import Settings
from backend_core.storage import connect

logger = logging.getLogger(__name__)


def requeue_interrupted(connection: sqlite3.Connection) -> int:
    """Put jobs that were mid-render when the process died back in the queue.

    ⚠️ Required by ADR-0015, and it is what makes restarting safe. A job left `running` is a
    session stuck in `rendering` for ever — the screen shows a spinner nobody can resolve,
    because `rendering` has no edge back and no worker will ever pick that job up again.

    Retrying is safe because a result is written to a path named after the **job**
    (`images.store_result`), so a second attempt replaces the first rather than adding to it.
    """
    requeued = jobs.requeue_running(connection)
    if requeued:
        logger.warning("requeued %d render job(s) interrupted by a restart", requeued)
    return requeued


async def run(app: FastAPI, poll_interval_s: float) -> None:
    """Poll for work until cancelled.

    Polling rather than a notification: the queue lives in the same SQLite file this process
    already opens, and at a few dozen renders a day a wake-up per second costs nothing next
    to the machinery a notification channel would add (ADR-0015, 선택지 C).

    ⚠️ The app is threaded through for one reason: the engine is resolved by
    `deps.resolve_ai_client`, which honours `app.dependency_overrides`. Calling the provider
    directly gave the worker the **real** HTTP client even under a test that had substituted
    a fake — see that function.
    """
    settings = deps.settings()
    while True:
        try:
            # ⚠️ `abandon_on_cancel=True`, or shutdown is not a shutdown. The default is
            # `False`, which makes cancellation **wait for the thread to return** — up to
            # `render_timeout_s` (300s) for an in-flight render. Every deploy would stall for
            # the length of whatever was drawing, which is the opposite of what
            # `lifespan_task` promises below. Abandoning is safe because the job stays
            # `running` and the next startup requeues it.
            done = await anyio.to_thread.run_sync(_drain_one, app, settings, abandon_on_cancel=True)
        except Exception:
            # ⚠️ The loop must outlive any single job. An unhandled error here kills the
            # background task and every later render silently never runs — the failure would
            # show up as "finalize works but nothing ever completes", days later.
            logger.exception("render worker iteration failed; continuing")
            done = False
        if not done:
            await anyio.sleep(poll_interval_s)


def _drain_one(app: FastAPI, settings: Settings) -> bool:
    """One iteration, on a worker thread. True when something was rendered."""
    with connect(settings.db_path) as connection:
        engine = deps.resolve_ai_client(app)
        return (
            render.run_one(
                connection,
                engine,
                settings.image_dir,
                timedelta(days=settings.retention_result_d),
            )
            is not None
        )


@contextlib.asynccontextmanager
async def lifespan_task(app: FastAPI, poll_interval_s: float, enabled: bool) -> AsyncIterator[None]:
    """Run the worker for as long as the app is up, when it is turned on.

    ⚠️ `enabled` exists for the test suite, and defaults to **on** so a deployment cannot
    forget it. Almost every test starts the app and immediately asserts on a job's state;
    a worker polling underneath would flip `queued` to `done` between the request and the
    assertion, and the test would fail depending on how fast the machine is. Tests that mean
    to exercise the worker turn it on and inject a fake engine.

    Cancelled on shutdown rather than joined: a render in flight can take minutes, and
    holding a container's shutdown open for that turns every deploy into a stall. The job it
    was running stays `running` and the next startup requeues it.
    """
    if not enabled:
        logger.info("render worker disabled by configuration")
        yield
        return

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(run, app, poll_interval_s)
        try:
            yield
        finally:
            tasks.cancel_scope.cancel()

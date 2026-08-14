"""Running one render job.

ADR-0015 puts the worker inside the backend process. This module is the part that does the
work for **one** job; the loop that finds jobs lives in `api.worker`, because the loop needs
the app's lifespan and this does not — which is what lets the whole of a render be tested
without starting a server.

⚠️ Serial execution is **not** enforced here. `jobs.next_queued` refuses to hand out work
while anything is `running`, so the rule holds however many callers exist. A loop that
checked "am I already busy" would lose the rule the moment a second worker appeared, and
there is one GPU — a second concurrent render is not slower, it is two OOMs
(AGENTS.md 설계 제약).

⚠️ FastAPI-free, and an ordinary `def`: this blocks on both SQLite and an HTTP call.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from pathlib import Path

from backend_core import images, jobs, session_flow, sessions
from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError, GenerationTimeoutError
from backend_core.models import (
    Error,
    ErrorCode,
    ImageRenderRequest,
    ImageSpec,
    JobResult,
    Session,
)

logger = logging.getLogger(__name__)

COMIC_SPEC = ImageSpec(width=3456, height=2304)
"""기획서 10.2. 3456 x 2304, so each of the six cells is 1152 x 1152.

⚠️ **The caller owns the spec, and this is that single constant** (미결정_대장 N16). The
engine deliberately does not derive the size from the output type — that would put 기획서
10.2's numbers in two places, and the first edit to one of them would go unnoticed. Keeping
one constant on this side is what makes a wrong `spec` unbuildable rather than merely
unlikely.
"""

SINGLE_AD_SPEC = ImageSpec(width=1088, height=1088)
"""잠정값 (미결정_대장 A절 8번, 잠정 진행). The comic size is fixed; this one is not."""

RESULT_RETENTION = timedelta(days=7)
"""세션_보관_정책 2절. Written onto the result so a client knows when the link dies; the
batch that actually deletes is a separate job (08-26)."""


def run_one(
    connection: sqlite3.Connection,
    engine: AiEngineClient,
    image_dir: str | Path,
) -> str | None:
    """Take the next queued job, render it, and record the outcome. Returns its id, or
    `None` when there was nothing to do.

    ⚠️ Every exit writes a terminal state. A job left `running` is a session stuck in
    `rendering` forever — the user sees a spinner that never resolves and there is no path
    out, because `rendering` has no edge back.
    """
    claimed = jobs.next_queued(connection)
    if claimed is None:
        return None

    job_id, session_id = claimed
    jobs.mark_running(connection, job_id)
    logger.info("rendering job %s for session %s", job_id, session_id)

    found = sessions.for_owner_of_job(connection, session_id)
    if found is None:  # pragma: no cover - a job cannot outlive its session today
        jobs.mark_failed(connection, job_id, Error(code="INTERNAL", message="세션이 없습니다."))
        return job_id

    user_id, session, was = found
    if session.draft is None:  # pragma: no cover - finalize is unreachable without a draft
        _fail(connection, user_id, session, was, job_id, "INTERNAL", "시안이 없습니다.")
        return job_id

    spec = COMIC_SPEC if session.output_type == "comic" else SINGLE_AD_SPEC
    try:
        payload = engine.render_image(
            ImageRenderRequest(
                output_type=session.output_type,
                brief=session.brief,
                draft=session.draft,
                spec=spec,
            )
        )
    except GenerationTimeoutError as exc:
        _fail(connection, user_id, session, was, job_id, "GENERATION_TIMEOUT", str(exc))
        return job_id
    except AiEngineUnavailableError as exc:
        _fail(connection, user_id, session, was, job_id, "UPSTREAM_UNAVAILABLE", str(exc))
        return job_id

    at = sessions.now()
    jobs.mark_done(
        connection,
        job_id,
        JobResult(
            image_url=images.store_result(image_dir, job_id, payload),
            width=spec.width,
            height=spec.height,
            expires_at=at + RESULT_RETENTION,
        ),
    )
    sessions.save(connection, user_id, session_flow.complete(session, at), was)
    return job_id


def _fail(
    connection: sqlite3.Connection,
    user_id: str,
    session: Session,
    was: sessions.Precondition,
    job_id: str,
    code: ErrorCode,
    message: str,
) -> None:
    """Both layers, in this order.

    ⚠️ The job is marked first. If the process dies between the two writes, a `failed` job
    beside a `rendering` session is recoverable — startup can read the job and finish the
    session. The other order leaves a `failed` session with a `running` job, and nothing can
    tell whether the render ever happened.
    """
    logger.warning("render job %s failed: %s", job_id, message)
    jobs.mark_failed(connection, job_id, Error(code=code, message=message))
    sessions.save(connection, user_id, session_flow.fail(session, sessions.now()), was)

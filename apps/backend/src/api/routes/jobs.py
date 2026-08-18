"""Job polling — the only asynchronous route in the system.

Contract: packages/contracts/openapi.yaml, the `jobs` tag.

⚠️ **A failed render is a 200.** The read succeeded; the job failed. Turning that into a 4xx
or 5xx would leave the client unable to tell "I could not reach the server" from "the
picture could not be made", and those need different screens (API_계약.md 2.1절).
"""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import FileResponse

from api import deps
from api.errors import not_found
from backend_core import images, jobs
from backend_core.accounts import Account
from backend_core.config import Settings
from backend_core.models import Job

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

JobId = Annotated[str, Path(alias="jobId")]
"""⚠️ Named as the contract names it. See `api.routes.sessions.SessionId` for why the
Python name would otherwise reach the published spec and contradict `openapi.yaml`."""


@router.get("/{jobId}")
def get_job(
    job_id: JobId,
    response: Response,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    settings: Annotated[Settings, Depends(deps.settings)],
) -> Job:
    """Where the render has got to. Recoverable by `jobId` after closing the browser.

    ⚠️ **The server sets the polling interval, through `Retry-After`.** The contract asks
    clients not to hard-code one, and that only works if we actually send it: a client
    following a hard-coded 3s cannot be slowed down when the queue backs up, and the extra
    load then lands exactly when there is least room for it.

    Only on `queued` and `running` — a finished job has no next poll, and a `Retry-After` on
    one would invite a client to keep asking forever.
    """
    job = jobs.for_user(connection, account.user_id, job_id)
    if job is None:
        # 404 for someone else's job as well as a missing one, same as sessions (INV-9).
        not_found("잡을 찾을 수 없습니다.")

    if job.status in ("queued", "running"):
        response.headers["Retry-After"] = str(settings.job_poll_interval_s)
    return job


@router.get(
    "/{jobId}/image",
    response_class=FileResponse,
    responses={200: {"content": {"image/webp": {}}}},
)
def get_job_image(
    job_id: JobId,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    settings: Annotated[Settings, Depends(deps.settings)],
) -> FileResponse:
    """The rendered image, as bytes. This is what `JobResult.imageUrl` points at.

    ⚠️ **Hung off the job rather than the session**, because the file is named after the job
    (`images.store_result`) — which is what makes a retried render replace its predecessor
    instead of accumulating one file per attempt (ADR-0015). INV-3 currently holds a session
    to one render, so a session-shaped path would work today, but that invariant is still
    `Proposed` (ADR-0006) and 기획서 18.2 #13 already schedules its review.

    Ownership is the job's, and the job's is the session's: `jobs.for_user` answers `None`
    for a stranger's job exactly as it does for one that does not exist (INV-9).

    A job that is queued, running or failed has no file, and neither does one whose seven
    days are up (세션_보관_정책.md 2절) — both are 404. The screen does not need this route
    to learn about expiry; `JobResult.expiresAt` says when it happens, ahead of time.
    """
    if jobs.for_user(connection, account.user_id, job_id) is None:
        not_found("잡을 찾을 수 없습니다.")

    path = images.find_result(settings.image_dir, job_id)
    if path is None:
        not_found("결과 이미지를 찾을 수 없습니다.")

    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": images.CACHE_CONTROL},
    )

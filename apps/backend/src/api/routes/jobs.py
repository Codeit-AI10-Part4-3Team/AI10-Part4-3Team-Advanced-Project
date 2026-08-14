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

from api import deps
from api.errors import not_found
from backend_core import jobs
from backend_core.accounts import Account
from backend_core.config import Settings
from backend_core.models import Job

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

JobId = Annotated[str, Path(alias="jobId")]
"""⚠️ Named as the contract names it. See `api.routes.sessions.SessionId` for why the
Python name would otherwise reach the published spec and contradict `openapi.yaml`."""


@router.get("/{jobId}", response_model=Job)
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

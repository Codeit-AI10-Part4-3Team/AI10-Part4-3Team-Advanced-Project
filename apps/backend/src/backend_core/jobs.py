"""Render jobs: the one asynchronous thing in the system.

Everything up to `finalize` answers synchronously. Past it, an image takes tens of seconds
and holding the request open would hit a timeout before the picture existed (API_계약.md
2.1절), so finalize accepts the work and the client polls.

**One job at a time, and that is a hardware fact, not a tuning choice.** There is one GPU
(AGENTS.md 설계 제약); a second concurrent render does not run twice as fast, it makes both
run out of VRAM. `queuePosition` exists because of it, and it is what the screen shows
instead of a progress bar that would have nothing to report.

⚠️ Ownership is carried on the job, not looked up through the session. A `jobId` is
guessable in exactly the way a `sessionId` is, so `for_user` takes the requester the same
way `sessions.for_user` does — the contract answers 404 here too, for the same reason
(INV-9).

⚠️ FastAPI-free, ordinary `def`s: this is blocking SQLite I/O (API_계약.md 2.2절).
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from backend_core.models import Error, Job, JobResult, JobStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id     TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    session_id TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document   TEXT NOT NULL
)
"""

# ⚠️ The queue is ordered by `(created_at, job_id)` in three places below, written out each
# time rather than interpolated from a constant. An f-string in a SQL statement is a pattern
# a reader has to check for injection every time they meet it, and this file has nothing to
# gain from it — the ordering is four words. `job_id` breaks the tie so two jobs accepted in
# the same clock tick still have a stable order; without it `queuePosition` could swap
# between two polls and the screen would count backwards.


def new_job_id() -> str:
    """A job id is a plain string in the contract, not a UUID field — but it is generated
    like one. It is handed to a client and used to fetch a result, so a sequential id would
    let anyone read the next person's render by adding one."""
    return str(uuid4())


def enqueue(
    connection: sqlite3.Connection, user_id: str, session_id: str, job_id: str, created_at: str
) -> Job:
    """Accept the render. The job starts `queued` and nothing renders yet."""
    job = Job(job_id=job_id, status="queued")
    connection.execute(
        """
        INSERT INTO jobs (job_id, user_id, session_id, status, created_at, document)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, user_id, session_id, job.status, created_at, job.model_dump_json(by_alias=True)),
    )
    connection.commit()
    return job


def _store(connection: sqlite3.Connection, job_id: str, job: Job) -> Job:
    connection.execute(
        "UPDATE jobs SET status = ?, document = ? WHERE job_id = ?",
        (job.status, job.model_dump_json(by_alias=True), job_id),
    )
    connection.commit()
    return job


def mark_running(connection: sqlite3.Connection, job_id: str) -> Job:
    return _store(connection, job_id, Job(job_id=job_id, status="running"))


def mark_done(connection: sqlite3.Connection, job_id: str, result: JobResult) -> Job:
    return _store(connection, job_id, Job(job_id=job_id, status="done", result=result))


def mark_failed(connection: sqlite3.Connection, job_id: str, error: Error) -> Job:
    """A failed render is still a job that answers 200 on read.

    The failure travels in `error.code`, not in the HTTP status: making it a 4xx or 5xx
    would leave the client unable to tell "I could not read the job" from "the job failed"
    (API_계약.md 2.1절).
    """
    return _store(connection, job_id, Job(job_id=job_id, status="failed", error=error))


def for_user(connection: sqlite3.Connection, user_id: str, job_id: str) -> Job | None:
    """One job, if it is this user's, with `queuePosition` filled in when it is waiting.

    ⚠️ The position is **computed on read, never stored.** A stored one would be wrong the
    moment anything ahead of it finished, and a queue position that only moves when someone
    refreshes twice is worse than none.
    """
    row = connection.execute(
        "SELECT status, created_at, job_id, document FROM jobs WHERE job_id = ? AND user_id = ?",
        (job_id, user_id),
    ).fetchone()
    if row is None:
        return None

    job = Job.model_validate_json(row["document"])
    if job.status == "queued":
        job.queue_position = _ahead_of(connection, row["created_at"], row["job_id"])
    return job


def _ahead_of(connection: sqlite3.Connection, created_at: str, job_id: str) -> int:
    """How many unfinished jobs arrived before this one.

    `running` counts too: a job being rendered right now is genuinely ahead in the queue,
    and leaving it out would show `queuePosition: 0` to someone who still has a full render
    to wait through.
    """
    row = connection.execute(
        """
        SELECT COUNT(*) AS ahead FROM jobs
        WHERE status IN ('queued', 'running')
          AND (created_at, job_id) < (?, ?)
        """,
        (created_at, job_id),
    ).fetchone()
    return int(row["ahead"])


def next_queued(connection: sqlite3.Connection) -> tuple[str, str] | None:
    """The job the worker should pick up next, as `(job_id, session_id)`.

    Returns `None` while something is already `running` — the serial-render rule lives here
    rather than in the worker, so a second worker process cannot break it by existing.
    """
    running = connection.execute("SELECT 1 FROM jobs WHERE status = 'running' LIMIT 1").fetchone()
    if running is not None:
        return None
    row = connection.execute(
        """
        SELECT job_id, session_id FROM jobs WHERE status = 'queued'
        ORDER BY created_at ASC, job_id ASC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return row["job_id"], row["session_id"]


def requeue_running(connection: sqlite3.Connection) -> int:
    """Move every `running` job back to `queued`. Returns how many moved.

    Called once at startup (api.worker). A `running` job at that moment cannot be running —
    the only process that could have been rendering it is the one that just started — so it
    is the residue of a crash or a deploy, and leaving it there strands the session in
    `rendering` for ever.

    ⚠️ Safe only because a retry is idempotent: the result file is named after the job, so a
    second attempt overwrites the first (ADR-0015).
    """
    # Read the ids first: the stored document carries the job id, so each row needs its own
    # value and there is no single UPDATE that can write them all.
    stranded = [
        row["job_id"]
        for row in connection.execute("SELECT job_id FROM jobs WHERE status = 'running'")
    ]
    for job_id in stranded:
        _store(connection, job_id, Job(job_id=job_id, status="queued"))
    return len(stranded)


def status_of(connection: sqlite3.Connection, job_id: str) -> JobStatus | None:
    row = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return None if row is None else str(row["status"])  # type: ignore[return-value]

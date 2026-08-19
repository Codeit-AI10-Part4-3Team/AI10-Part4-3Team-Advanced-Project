"""보존 기간 정리: **what** gets deleted when it expires.

세션_보관_정책.md 2절 sets the periods and says the part that matters here:

> 만료된 데이터는 **삭제하는 코드가 있어야 합니다.** 기간을 문서에만 적어 두면 아무것도
> 지워지지 않습니다.

Until this module existed, nothing expired. `Brief.productImageUrl` was documented to go
empty on expiry and never did, and `JobResult.expiresAt` named a time after which the link
was supposed to die while the file stayed on disk (API_계약.md 8.4절).

This module owns *what*; `api.sweeper` owns *when*. The split is the same one
`backend_core.render` and `api.worker` use, and for the same reason: the whole policy can be
tested without starting a server or waiting a day.

Three rules shape the code.

- **Files are not rows.** Images live on disk with only their paths in SQLite (ADR-0010), so
  deleting a row cannot take its file along. Every deletion here does both, files first --
  a row without its file is a 404 the contract already describes, while a file without its
  row is invisible garbage that nothing will ever collect.
- **A promise already made outranks the period.** `JobResult.expiresAt` went to a client as
  a fact. A session may not be deleted while it still owns a result whose promised time has
  not come, even if the session itself is past its own period -- deleting the session makes
  the result unreachable (INV-9 turns an orphan into a 404), which is the same broken
  promise by a different route. See `_deadline`.
- **Blanking is not editing.** When a photo expires the brief's reference becomes `""`, and
  that write must not touch `revision` or `updated_at` (`sessions.overwrite_document`).

⚠️ Logs are **not** swept here. 세션_보관_정책 2절 gives them 30 days, but this application
writes them to stdout and the container runtime owns them from there; there is no log store
in SQLite to delete from. Rotation belongs with the deployment, not with this batch.

⚠️ Keep this module FastAPI-free, like the rest of backend_core.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from backend_core import images, jobs, sessions
from backend_core.models.job import Job
from backend_core.models.session import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    """The periods from 세션_보관_정책 2절, as values rather than constants.

    The policy says the periods are settings ("기간 값과 배치 주기는 설정값입니다"), so the
    numbers arrive from `Settings` and this dataclass only carries them. The defaults match
    the document so a test can construct one without repeating the table.
    """

    photo: timedelta = timedelta(hours=24)
    """업로드 제품 사진. **Measured from upload, not from render.** A session that never
    reaches finalize would otherwise keep its photo for ever -- the policy calls that out."""

    session: timedelta = timedelta(days=7)
    """브리프와 시안(텍스트). From creation, for the same reason the photo is: from the last
    edit would mean an idle-but-touched session never expires."""


@dataclass
class SweepReport:
    """What one pass actually removed. Returned so the caller can log a number, and so a
    test can assert on the count rather than on log text."""

    photos: int = 0
    """Expired uploads deleted, with the brief reference blanked."""

    results: int = 0
    """Result images deleted, at the time their own `expiresAt` promised."""

    sessions: int = 0
    """Sessions removed, with their jobs and any remaining files."""

    def touched(self) -> bool:
        return bool(self.photos or self.results or self.sessions)


def sweep(
    connection,
    image_dir: str | Path,
    policy: Policy,
    now: datetime,
) -> SweepReport:
    """Delete everything past its period. Safe to run at any time, and to run twice.

    Idempotent by construction: every step asks "is this expired and still here", so a second
    pass over the same data finds nothing. That matters because the batch runs on a timer
    inside a process that restarts on every deploy -- two passes an hour apart are normal.

    Order is deliberate. Whole sessions go first so the later passes have less to look at,
    and so a session's photo is removed once rather than twice.
    """
    report = SweepReport()

    for session_id, session in sessions.expired_candidates(connection):
        owned = jobs.for_session(connection, session_id)
        if _deadline(session, owned, policy) > now:
            continue
        _drop_session(connection, image_dir, session_id, session, owned)
        report.sessions += 1

    for job_id, job in jobs.all_results(connection):
        if job.result is None or job.result.expires_at > now:
            continue
        if _unlink(images.find_result(image_dir, job_id)):
            report.results += 1

    for _, session in sessions.expired_candidates(connection):
        if session.created_at + policy.photo > now:
            continue
        if not session.brief.product_image_url:
            continue
        _unlink(images.find(image_dir, session.session_id))
        session.brief.product_image_url = ""
        sessions.overwrite_document(connection, session)
        report.photos += 1

    if report.touched():
        logger.info(
            "retention sweep removed photos=%d results=%d sessions=%d",
            report.photos,
            report.results,
            report.sessions,
        )
    return report


def _deadline(session: Session, owned: list[tuple[str, Job]], policy: Policy) -> datetime:
    """When this session may be removed: its own period, or its last promise, whichever later.

    ⚠️ The `max` is the whole point. A session rendered on its sixth day owns a result
    promised for another seven, and `expiresAt` was **sent to a client** (contract,
    `JobResult`). Removing the session at its own seven days would take the job row with it,
    and a result whose session is gone is a 404 to everyone (INV-9) -- the link dies before
    the time we published for it.
    """
    own = session.created_at + policy.session
    promised = [job.result.expires_at for _, job in owned if job.result is not None]
    return max([own, *promised])


def _drop_session(
    connection,
    image_dir: str | Path,
    session_id: str,
    session: Session,
    owned: list[tuple[str, Job]],
) -> None:
    """Remove a session and everything that belongs to it. Files first, then rows.

    ⚠️ If this dies halfway the next pass finishes the job, because the leftovers are still
    expired. The reverse order would not recover: rows gone, files orphaned, and nothing left
    that knows the files existed.
    """
    for job_id, _ in owned:
        _unlink(images.find_result(image_dir, job_id))
    _unlink(images.find(image_dir, session.session_id))

    for job_id, _ in owned:
        jobs.delete(connection, job_id)
    sessions.delete(connection, session_id)


def _unlink(path: Path | None) -> bool:
    """Delete a file if it is there. True when something was removed.

    A missing file is the normal case on a second pass, not an error. A file we cannot delete
    is logged and skipped rather than raised: one unreadable path must not stop the rest of
    the sweep, or a single bad file freezes retention for everything.
    """
    if path is None:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("retention could not delete %s", path)
        return False
    return True

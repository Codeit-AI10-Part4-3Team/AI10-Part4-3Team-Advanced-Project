"""보존 기간 정리: what actually gets deleted, and what may not be.

세션_보관_정책 2절 says "만료된 데이터는 삭제하는 코드가 있어야 합니다. 기간을 문서에만
적어 두면 아무것도 지워지지 않습니다." These tests are the other half of that sentence — a
batch nobody exercises is a period nobody enforces.

⚠️ Every test drives the clock through `now` rather than sleeping. The periods are a day and
a week; a test that waited would never run.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend_core import images, jobs, retention, sessions
from backend_core.models import Brief, BriefMeta, FieldMeta, Session
from backend_core.models.job import JobResult
from backend_core.storage import connect, init_schema

USER = "11111111-1111-4111-8111-111111111111"

POLICY = retention.Policy(photo=timedelta(hours=24), session=timedelta(days=7))


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "retention.sqlite") as conn:
        init_schema(conn)
        yield conn


def _meta() -> FieldMeta:
    return FieldMeta(filled_by="user", visibility="editable")


def _session(at: datetime, image_url: str = "photo.png") -> Session:
    return Session(
        session_id=sessions.new_session_id(),
        state="brief_ready",
        output_type="single_ad",
        revision=0,
        message_mode="normal",
        brief=Brief(
            product_image_url=image_url,
            product_name="테스트 제품",
            selling_point="수분감이 오래 갑니다",
            note="",
            category="생활용품",
            target="30대",
            art_style="",
        ),
        brief_meta=BriefMeta(
            product_image_url=_meta(),
            product_name=_meta(),
            selling_point=_meta(),
            note=_meta(),
            category=_meta(),
            target=_meta(),
            art_style=_meta(),
        ),
        created_at=at,
        updated_at=at,
    )


def _with_photo(connection: sqlite3.Connection, image_dir: Path, at: datetime) -> Session:
    """A stored session whose upload is actually on disk, so deletion is observable."""
    session = _session(at)
    url = images.store(image_dir, session.session_id, _real_png())
    session.brief.product_image_url = url
    sessions.create(connection, USER, session)
    return session


def _real_png() -> bytes:
    """`images.store` validates: a real header and a short edge of at least 512px."""
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return len(payload).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    side = 600
    header = (side).to_bytes(4, "big") + (side).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * side for _ in range(side))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _done_job(
    connection: sqlite3.Connection,
    image_dir: Path,
    session: Session,
    at: datetime,
    expires: datetime,
) -> str:
    """A finished render belonging to `session`, with its result file written."""
    job_id = jobs.new_job_id()
    jobs.enqueue(connection, USER, str(session.session_id), job_id, at.isoformat())
    jobs.mark_running(connection, job_id)
    url = images.store_result(image_dir, job_id, b"not-really-a-webp")
    jobs.mark_done(
        connection,
        job_id,
        JobResult(image_url=url, width=1088, height=1088, expires_at=expires),
    )
    return job_id


# ---- 업로드 사진: 24시간 -------------------------------------------------------------------


def test_a_photo_survives_its_first_day(connection: sqlite3.Connection, tmp_path: Path) -> None:
    at = sessions.now()
    session = _with_photo(connection, tmp_path, at)

    report = retention.sweep(connection, tmp_path, POLICY, at + timedelta(hours=23))

    assert report.photos == 0
    assert images.find(tmp_path, session.session_id) is not None


def test_an_expired_photo_is_deleted_and_its_reference_blanked(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """Both halves, because either one alone is a bug the screen shows.

    The file alone left behind is personal data past its period. The reference alone left
    behind is a broken `<img>`: the contract says an expired photo reads as an empty string
    so the screen can branch before drawing (API_계약.md 8.4절).
    """
    at = sessions.now()
    session = _with_photo(connection, tmp_path, at)

    report = retention.sweep(connection, tmp_path, POLICY, at + timedelta(hours=25))

    assert report.photos == 1
    assert images.find(tmp_path, session.session_id) is None
    stored = sessions.for_user(connection, USER, session.session_id)
    assert stored is not None
    assert stored[0].brief.product_image_url == ""


def test_blanking_a_photo_does_not_touch_revision_or_updated_at(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """⚠️ The batch is not a user edit, and the client can tell.

    `revision` is the optimistic-lock token: bumping it makes the next patch from an open
    screen fail with a conflict nobody can explain. `updated_at` orders the session list, so
    bumping it reshuffles somebody's list because a batch ran overnight.
    """
    at = sessions.now()
    session = _with_photo(connection, tmp_path, at)

    retention.sweep(connection, tmp_path, POLICY, at + timedelta(hours=25))

    stored = sessions.for_user(connection, USER, session.session_id)
    assert stored is not None
    assert stored[0].revision == session.revision
    assert stored[0].updated_at == session.updated_at


# ---- 세션(브리프와 시안): 7일 --------------------------------------------------------------


def test_an_expired_session_takes_its_jobs_and_files_with_it(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    at = sessions.now()
    session = _with_photo(connection, tmp_path, at)
    job_id = _done_job(connection, tmp_path, session, at, expires=at + timedelta(days=7))

    report = retention.sweep(connection, tmp_path, POLICY, at + timedelta(days=8))

    assert report.sessions == 1
    assert sessions.for_user(connection, USER, session.session_id) is None
    assert jobs.for_user(connection, USER, job_id) is None
    assert images.find_result(tmp_path, job_id) is None
    assert images.find(tmp_path, session.session_id) is None


def test_a_session_outlives_its_period_while_a_promised_result_is_still_live(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """⚠️ The rule that keeps the contract honest.

    `JobResult.expiresAt` went to a client as a fact. A session rendered on its sixth day
    owns a result promised for another seven, and deleting the session at its own seven days
    would take the job row with it — after which the result is a 404 to everyone (INV-9).
    The link would die four days before the time we published for it.
    """
    at = sessions.now()
    session = _with_photo(connection, tmp_path, at)
    rendered = at + timedelta(days=6)
    job_id = _done_job(
        connection, tmp_path, session, rendered, expires=rendered + timedelta(days=7)
    )

    report = retention.sweep(connection, tmp_path, POLICY, at + timedelta(days=8))

    assert report.sessions == 0
    assert sessions.for_user(connection, USER, session.session_id) is not None
    assert images.find_result(tmp_path, job_id) is not None

    # ...and it does go once the promise has been kept.
    assert retention.sweep(connection, tmp_path, POLICY, rendered + timedelta(days=8)).sessions == 1


# ---- 결과 이미지: 자기 expiresAt ------------------------------------------------------------


def test_a_result_image_dies_at_the_time_that_was_published(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """Not at the session's period — at the moment the client was told."""
    at = sessions.now()
    session = _with_photo(connection, tmp_path, at)
    expires = at + timedelta(days=3)
    job_id = _done_job(connection, tmp_path, session, at, expires=expires)

    assert retention.sweep(connection, tmp_path, POLICY, expires - timedelta(hours=1)).results == 0
    assert images.find_result(tmp_path, job_id) is not None

    assert retention.sweep(connection, tmp_path, POLICY, expires + timedelta(hours=1)).results == 1
    assert images.find_result(tmp_path, job_id) is None


# ---- 되풀이 -------------------------------------------------------------------------------


def test_a_second_pass_finds_nothing_left_to_do(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """The sweeper runs at startup and on a timer, so two passes an hour apart are normal.

    A pass that deleted twice would raise on a missing file; one that counted twice would
    make the log a lie.
    """
    at = sessions.now()
    session = _with_photo(connection, tmp_path, at)
    _done_job(connection, tmp_path, session, at, expires=at + timedelta(days=7))
    later = at + timedelta(days=8)

    first = retention.sweep(connection, tmp_path, POLICY, later)
    second = retention.sweep(connection, tmp_path, POLICY, later)

    assert first.touched()
    assert not second.touched()

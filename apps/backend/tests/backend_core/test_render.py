"""The render worker: one job at a time, and every exit terminal.

This is what closes S2's "`created` 부터 `completed` 까지" and S6's "폴링으로 `done` 도달".
Until this ran, `rendering -> completed` had never been executed once.

⚠️ The loop is not tested here — `render.run_one` is one iteration and takes its connection
and engine as arguments, which is what lets the whole of a render be exercised without
starting a server or waiting on a poll interval.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import RENDERED_WEBP, FakeAiEngine, draft_for

from backend_core import jobs, render, session_flow, sessions
from backend_core.ai_client import AiEngineUnavailableError, GenerationTimeoutError
from backend_core.models import Brief, BriefMeta, FieldMeta, Session
from backend_core.storage import connect, init_schema

USER = "11111111-1111-4111-8111-111111111111"
OTHER_USER = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with connect(tmp_path / "render.sqlite") as conn:
        init_schema(conn)
        yield conn


def _meta() -> FieldMeta:
    return FieldMeta(filled_by="user", visibility="editable")


def _finalized(connection: sqlite3.Connection, user_id: str = USER) -> tuple[str, str]:
    """A session sitting in `rendering` with a queued job, as `finalize` leaves it."""
    at = sessions.now()
    session = Session(
        session_id=sessions.new_session_id(),
        state="draft_ready",
        output_type="single_ad",
        revision=0,
        message_mode="normal",
        brief=Brief(
            # Never opened by anything under test — the render sends the brief to the
            # engine, which in these tests is a fake. A real path would suggest otherwise.
            product_image_url="photo.png",
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
        draft=draft_for("single_ad"),
        created_at=at,
        updated_at=at,
    )
    sessions.create(connection, user_id, session)
    _, was = sessions.for_user(connection, user_id, session.session_id)  # type: ignore[misc]

    job_id = jobs.new_job_id()
    sessions.save(connection, user_id, session_flow.finalize(session, job_id, at), was)
    jobs.enqueue(connection, user_id, str(session.session_id), job_id, at.isoformat())
    return str(session.session_id), job_id


def test_a_render_takes_the_session_all_the_way_to_completed(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """The transition S2's completion condition names, executed for the first time."""
    session_id, job_id = _finalized(connection)

    assert render.run_one(connection, FakeAiEngine(), tmp_path) == job_id

    job = jobs.for_user(connection, USER, job_id)
    assert job is not None
    assert job.status == "done"
    assert job.result is not None
    assert Path(job.result.image_url).read_bytes() == RENDERED_WEBP

    found = sessions.for_owner_of_job(connection, session_id)
    assert found is not None
    assert found[1].state == "completed"


def test_nothing_to_do_is_not_an_error(connection: sqlite3.Connection, tmp_path: Path) -> None:
    assert render.run_one(connection, FakeAiEngine(), tmp_path) is None


def test_only_one_job_runs_at_a_time(connection: sqlite3.Connection, tmp_path: Path) -> None:
    """⚠️ The rule that keeps one GPU from being asked for two renders (ADR-0015).

    It lives in `jobs.next_queued`, not in the loop, so a second worker cannot break it by
    existing. Here: two queued jobs, one call — the second is not touched, because the first
    is still `running` when the second would be picked.
    """
    _, first = _finalized(connection)
    _, second = _finalized(connection)

    jobs.mark_running(connection, first)

    assert render.run_one(connection, FakeAiEngine(), tmp_path) is None
    assert jobs.status_of(connection, second) == "queued"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (AiEngineUnavailableError("down"), "UPSTREAM_UNAVAILABLE"),
        (GenerationTimeoutError("slow"), "GENERATION_TIMEOUT"),
    ],
    ids=["outage", "timeout"],
)
def test_a_failed_render_ends_both_layers(
    connection: sqlite3.Connection, tmp_path: Path, failure: Exception, expected_code: str
) -> None:
    """⚠️ Both, and both terminal. A job left `running` is a session stuck in `rendering`
    for ever — `rendering` has no edge back and nothing would ever pick the job up again."""
    session_id, job_id = _finalized(connection)

    class Failing(FakeAiEngine):
        def render_image(self, request: object) -> bytes:  # type: ignore[override]
            raise failure

    render.run_one(connection, Failing(), tmp_path)

    job = jobs.for_user(connection, USER, job_id)
    assert job is not None and job.status == "failed"
    assert job.error is not None and job.error.code == expected_code

    found = sessions.for_owner_of_job(connection, session_id)
    assert found is not None and found[1].state == "failed"


def test_the_result_is_named_after_the_job_so_a_retry_replaces_it(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """ADR-0015 leans on this: startup requeues jobs left `running`, so a render can run
    twice. Naming the file after the job means the second attempt overwrites the first
    instead of leaving one file per attempt."""
    _, job_id = _finalized(connection)
    render.run_one(connection, FakeAiEngine(), tmp_path)

    results = list((Path(tmp_path) / "results").iterdir())

    assert [path.name for path in results] == [f"{job_id}.webp"]


def test_requeue_returns_interrupted_jobs_to_the_queue(connection: sqlite3.Connection) -> None:
    """A `running` job at startup cannot be running — the only process that could have been
    rendering it is the one just starting."""
    _, job_id = _finalized(connection)
    jobs.mark_running(connection, job_id)

    assert jobs.requeue_running(connection) == 1
    assert jobs.status_of(connection, job_id) == "queued"


def test_requeue_leaves_finished_jobs_alone(connection: sqlite3.Connection, tmp_path: Path) -> None:
    _, job_id = _finalized(connection)
    render.run_one(connection, FakeAiEngine(), tmp_path)

    assert jobs.requeue_running(connection) == 0
    assert jobs.status_of(connection, job_id) == "done"


def test_the_render_request_carries_the_size_the_output_type_demands(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """기획서 10.2's numbers live in one constant on this side, and the engine is told rather
    than left to derive them (미결정_대장 N16)."""
    _finalized(connection)
    engine = FakeAiEngine()

    render.run_one(connection, engine, tmp_path)

    assert engine.renders_requested[0].spec == render.SINGLE_AD_SPEC

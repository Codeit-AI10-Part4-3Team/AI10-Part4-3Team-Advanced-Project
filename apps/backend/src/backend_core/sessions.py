"""Session persistence.

ADR-0010 put every piece of durable state in one SQLite file, and S2's completion condition
is that a session survives a restart — so this is where "the work I did is still there"
either holds or does not.

**The row stores the whole `Session` model as JSON, plus the three columns a query needs.**
The alternative — a column per field — would spread one document across a table and a set
of nested tables (`brief`, `briefMeta`, `draft`, `panels`), and every contract change would
become a migration in a deployment that has no migration step (ADR-0011). The document is
written and read whole, which is also how the contract treats it: a patch returns the full
session, not a delta.

⚠️ The three columns are **derived from the document, in one place** (`save`). They exist
because SQL cannot filter or sort inside the JSON without depending on the JSON1 extension,
and duplication that only one function can create is duplication that cannot drift.

⚠️ Ownership lives here, not in the routes. `for_user` is the only way to read a session,
and it takes the requester's `user_id` as a required argument — so "forgot to check the
owner" is not a mistake this module lets a caller make (INV-9). A session that belongs to
someone else is indistinguishable from one that does not exist, which is the whole point:
403 would confirm the id is real.

⚠️ Keep this FastAPI-free, and keep every function an ordinary `def` — SQLite is blocking
I/O and FastAPI has to be free to run it in a threadpool (API_계약.md 2.2절).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from backend_core.models import Session, SessionSummary

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    state      TEXT NOT NULL,
    revision   INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    document   TEXT NOT NULL
)
"""
"""`state` and `revision` are duplicated out of the document, and they earn it.

They are not for reading — everything read comes from `document`. They exist so an update
can be **conditional on the version it was based on**, in one statement. Without that, every
route is a read-modify-write with a gap in the middle, and two requests that arrive together
both read the old state, both decide they are allowed, and both write (2026-08-14 실측).

Kept honest by `save` being the only writer: it derives both from the model it is given, so
there is exactly one line where they could diverge.
"""


class ConcurrentUpdateError(Exception):
    """Someone changed this session between our read and our write.

    ⚠️ Not the same as `RevisionConflictError`, which is a *client* holding a stale copy and
    saying so in its request. This one is two requests from the same client racing, where
    both carried the right revision and only one can be right by the time they land.
    """


INDEX = """
CREATE INDEX IF NOT EXISTS sessions_by_owner
    ON sessions (user_id, updated_at DESC)
"""
"""`GET /v1/sessions` filters by owner and sorts by recency; this is that query's index."""


def new_session_id() -> UUID:
    return uuid4()


def now() -> datetime:
    """One clock for the module, in UTC.

    Timestamps go to the wire and into `ORDER BY`. A naive local time would sort correctly
    on one machine and wrongly after a deploy to a VM in another zone.
    """
    return datetime.now(UTC)


@dataclass(frozen=True)
class Precondition:
    """What the session looked like when we read it.

    Carried from the read to the write so the update can refuse if anything moved in
    between. Taken by `read` rather than reconstructed later, because `session_flow` mutates
    the model in place and the original values are gone by the time `save` is called.
    """

    state: str
    revision: int


def create(connection: sqlite3.Connection, user_id: str, session: Session) -> Session:
    """Insert a brand-new session. Its id has never been seen, so there is nothing to race."""
    connection.execute(
        """
        INSERT INTO sessions (session_id, user_id, state, revision, updated_at, document)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(session.session_id),
            user_id,
            session.state,
            session.revision,
            session.updated_at.isoformat(),
            session.model_dump_json(by_alias=True),
        ),
    )
    connection.commit()
    return session


def save(
    connection: sqlite3.Connection,
    user_id: str,
    session: Session,
    was: Precondition,
) -> Session:
    """Write the session back, **only if it still looks the way we read it.**

    ⚠️ `was` is not optional and the `WHERE` clause is the point. Every route here is a
    read, a decision, and a write, and the state machine's guard runs on the value read at
    the start. Two requests arriving together both read `draft_ready`, both find the
    transition allowed, and both write — so `POST .../finalize` twice returned **two 202s and
    queued two renders** (2026-08-14 실측). That is INV-3, the cost defence, and one GPU pass
    per session is the whole of it.

    Making the update conditional moves the decision into the same statement as the write.
    The loser changes no rows, and the caller turns that into the 409 it should have got.

    The caller owns `updated_at`: a patch that changes nothing should still not silently move
    the timestamp, and only the caller knows whether anything changed.
    """
    cursor = connection.execute(
        """
        UPDATE sessions
           SET state = ?, revision = ?, updated_at = ?, document = ?
         WHERE session_id = ? AND user_id = ? AND state = ? AND revision = ?
        """,
        (
            session.state,
            session.revision,
            session.updated_at.isoformat(),
            session.model_dump_json(by_alias=True),
            str(session.session_id),
            user_id,
            was.state,
            was.revision,
        ),
    )
    connection.commit()
    if cursor.rowcount == 0:
        raise ConcurrentUpdateError(
            f"session {session.session_id} moved from {was.state!r}/r{was.revision} "
            "while this request was deciding what to do with it"
        )
    return session


def for_user(
    connection: sqlite3.Connection, user_id: str, session_id: UUID
) -> tuple[Session, Precondition] | None:
    """One session, if it is this user's, **with the version it was read at**.

    ⚠️ `None` covers both "no such session" and "not yours", deliberately and permanently.
    Separating them here would push the choice up to the route, and the first route to get
    it wrong would leak existence through a 403 (INV-9).

    Returning the `Precondition` alongside is what makes a conditional write possible at all:
    `session_flow` mutates the model in place, so by the time anyone calls `save` the values
    we read are gone. Handing them back together means a caller cannot forget to capture
    them — the only way to get a session is to get one of these too.
    """
    row = connection.execute(
        "SELECT document, state, revision FROM sessions WHERE session_id = ? AND user_id = ?",
        (str(session_id), user_id),
    ).fetchone()
    if row is None:
        return None
    session = Session.model_validate_json(row["document"])
    return session, Precondition(state=row["state"], revision=row["revision"])


def for_owner_of_job(
    connection: sqlite3.Connection, session_id: str
) -> tuple[str, Session, Precondition] | None:
    """A session looked up **without** a requester, for the render worker.

    ⚠️ The only function here that does not take `user_id`, and the exception needs its
    reason stated: the worker is not acting for a requester. It picked a job the server
    itself accepted, so there is nobody to check against — instead it *reads back* the owner
    and hands it to whatever writes next, so the write is still scoped to one user.

    Nothing reachable from HTTP may call this. Everything a request touches goes through
    `for_user`, which cannot be called without saying who is asking (INV-9).
    """
    row = connection.execute(
        "SELECT user_id, document, state, revision FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return (
        row["user_id"],
        Session.model_validate_json(row["document"]),
        Precondition(state=row["state"], revision=row["revision"]),
    )


def list_for_user(connection: sqlite3.Connection, user_id: str) -> list[SessionSummary]:
    """This user's sessions, newest first.

    Summaries, not sessions: the contract keeps the draft body out of the list view, and a
    list endpoint that shipped every draft would grow without bound as work accumulates.

    `productName` is read back out of the brief rather than stored beside it. It is the one
    summary field that does not exist on `Session` itself, and a copy in a column would be
    a second place for the product's name to live.

    ⚠️ **A row that will not parse is skipped, not raised.** This endpoint reads every
    session a user has, so validating them in one comprehension makes a single bad document
    take down the whole list — the user loses the way back to *all* their work because one
    of them is malformed, and there is no route that would let them delete the bad one.
    Logged rather than swallowed, because a document we wrote and cannot read back is a
    defect somewhere else.
    """
    rows = connection.execute(
        "SELECT session_id, document FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()

    summaries = []
    for row in rows:
        try:
            summaries.append(_summarise(Session.model_validate_json(row["document"])))
        except ValidationError:
            logger.exception("session %s will not parse; omitted from the list", row["session_id"])
    return summaries


def _summarise(session: Session) -> SessionSummary:
    return SessionSummary(
        session_id=session.session_id,
        state=session.state,
        output_type=session.output_type,
        product_name=session.brief.product_name,
        message_mode=session.message_mode,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def expired_candidates(connection: sqlite3.Connection) -> list[tuple[str, Session]]:
    """Every session, for the retention batch to judge. Newest first is irrelevant here.

    ⚠️ A full scan on purpose. The deadline is not a column -- `created_at` lives inside the
    JSON document, and the real deadline also depends on a session's job results (계약이
    `expiresAt` 으로 약속한 시각). Encoding that in SQL would put the policy in two places.
    At this size (a few dozen sessions a day) the scan costs nothing; if the table ever grows
    enough to matter, promote `created_at` to a column and index it -- and move the policy
    with it, not just the query.
    """
    rows = connection.execute("SELECT session_id, document FROM sessions").fetchall()
    return [(str(row["session_id"]), Session.model_validate_json(row["document"])) for row in rows]


def overwrite_document(connection: sqlite3.Connection, session: Session) -> None:
    """Replace the stored document in place, touching nothing else.

    ⚠️ Not `save`: that one takes a `Precondition` and is for user edits. This is the
    retention batch blanking an expired photo reference, and it must **not** bump `revision`
    or `updated_at`. `revision` is the client's optimistic-lock token -- moving it would make
    the next patch from an open screen fail with a conflict the user cannot explain.
    `updated_at` is "when the user last changed this", and the session list is ordered by it,
    so bumping it would reshuffle somebody's list because a batch ran at 4am.
    """
    connection.execute(
        "UPDATE sessions SET document = ? WHERE session_id = ?",
        (session.model_dump_json(by_alias=True), str(session.session_id)),
    )
    connection.commit()


def delete(connection: sqlite3.Connection, session_id: str) -> None:
    """Remove one session row. The caller deals with its files and jobs.

    Deliberately not a cascade: the files live outside SQLite (ADR-0010) and deleting a row
    cannot take them with it. A cascade would leave the disk filling up while the database
    looked clean -- exactly the failure the retention policy exists to prevent.
    """
    connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    connection.commit()

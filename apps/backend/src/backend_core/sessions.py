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

import sqlite3
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend_core.models import Session, SessionSummary

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    document   TEXT NOT NULL
)
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


def save(connection: sqlite3.Connection, user_id: str, session: Session) -> Session:
    """Write the session, creating it or replacing it wholesale.

    The caller owns `updated_at`: a patch that changes nothing should still not silently
    move the timestamp, and only the caller knows whether anything changed.
    """
    connection.execute(
        """
        INSERT INTO sessions (session_id, user_id, updated_at, document)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            updated_at = excluded.updated_at,
            document   = excluded.document
        """,
        (
            str(session.session_id),
            user_id,
            session.updated_at.isoformat(),
            session.model_dump_json(by_alias=True),
        ),
    )
    connection.commit()
    return session


def for_user(connection: sqlite3.Connection, user_id: str, session_id: UUID) -> Session | None:
    """One session, if it is this user's.

    ⚠️ `None` covers both "no such session" and "not yours", deliberately and permanently.
    Separating them here would push the choice up to the route, and the first route to get
    it wrong would leak existence through a 403 (INV-9).
    """
    row = connection.execute(
        "SELECT document FROM sessions WHERE session_id = ? AND user_id = ?",
        (str(session_id), user_id),
    ).fetchone()
    if row is None:
        return None
    return Session.model_validate_json(row["document"])


def list_for_user(connection: sqlite3.Connection, user_id: str) -> list[SessionSummary]:
    """This user's sessions, newest first.

    Summaries, not sessions: the contract keeps the draft body out of the list view, and a
    list endpoint that shipped every draft would grow without bound as work accumulates.

    `productName` is read back out of the brief rather than stored beside it. It is the one
    summary field that does not exist on `Session` itself, and a copy in a column would be
    a second place for the product's name to live.
    """
    rows = connection.execute(
        "SELECT document FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    return [_summarise(Session.model_validate_json(row["document"])) for row in rows]


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

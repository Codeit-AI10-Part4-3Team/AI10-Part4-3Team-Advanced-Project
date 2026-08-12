"""SQLite storage: connections and schema.

ADR-0010 puts every piece of durable state (accounts, sessions, briefs, drafts, jobs) in
one SQLite file, with images on local disk and only their paths in the database. This
module owns the file: how it is opened, and how its tables come to exist.

Two rules from the surrounding documents shape the code here:

- **The path is configuration, never a constant.** A hard-coded path splits local
  development from the VM deployment (ADR-0010).
- **This is blocking I/O.** Callers must stay ordinary `def` functions so FastAPI runs
  them in a threadpool. With a single worker, a blocking call on the event loop stalls
  every other request for its whole duration (API_계약.md 2.2절).

⚠️ Deliberately minimal: no WAL mode, no migration versioning, no connection pool.
ADR-0010 was accepted on the basis of one worker and one serial render, and its
re-examination signal says to move when `database is locked` is *observed*, not
anticipated. Add machinery when a document asks for it.

⚠️ Keep this module FastAPI-free, like the rest of backend_core.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    login_id      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
)
"""


@contextmanager
def connect(db_path: str | Path) -> Generator[sqlite3.Connection]:
    """Open one connection, and close it when the caller is done.

    A connection per operation rather than a shared one, because FastAPI runs sync
    handlers in a threadpool and sqlite3 connections are not safe to share across
    threads. Opening is cheap; the alternative is thread-local plumbing that buys nothing
    at this size (one worker, one serial render — 세션_보관_정책.md 6절).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        yield connection
    finally:
        connection.close()


def init_schema(connection: sqlite3.Connection) -> None:
    """Make the tables exist. Safe to call on every startup, and that is when it runs:
    the deployment path is `git pull` + `docker compose up`, with no separate migration
    step to hang one off (ADR-0011)."""
    connection.execute(SCHEMA)
    connection.commit()

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

    A connection per operation rather than a shared one. Opening is cheap; the alternative
    is thread-local plumbing that buys nothing at this size (one worker, one serial
    render — 세션_보관_정책.md 6절).

    ⚠️ `check_same_thread=False` is **required**, not a shortcut. FastAPI runs a sync
    generator dependency through anyio's threadpool, and the setup, the route body and the
    teardown are not guaranteed to land on the same worker thread. With sqlite3's default
    (`True`) that raises

        sqlite3.ProgrammingError: SQLite objects created in a thread can only be
        used in that same thread.

    and it does so **only under concurrency** — 2026-08-13 실측: 16 concurrent requests
    failed 182 of 200, while the same 200 sequentially all passed. A sequential test suite
    cannot see this, which is why `tests/api/test_concurrency.py` sends them in parallel.

    Turning the check off is safe here because a connection is never shared *between*
    requests: each caller opens its own and closes it, and within one request the steps run
    one after another. It would stop being safe the moment a connection is cached or
    handed to a background task — do not do that without reopening ADR-0010.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, check_same_thread=False)
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

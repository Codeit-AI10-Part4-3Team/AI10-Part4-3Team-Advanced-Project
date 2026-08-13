"""Accounts: seeding from configuration, and checking a password.

Signup is 501 for this cut (ADR-0008), so accounts only ever arrive one way: they are
seeded from `infra/.env` at startup. The credentials live in .env because this repository
is public; the *accounts* live in SQLite because ADR-0010 put them there. Those are not in
conflict — .env is the source, the database is the store.

⚠️ FastAPI-free by design, like the rest of backend_core.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from backend_core.config import SeedAccount

# Library defaults on purpose: 세션_보관_정책.md 1.2절 says to take them rather than tune
# parameters we cannot evaluate.
_hasher = PasswordHasher()

# Verified against a wrong password when the login id does not exist, so that a missing
# account costs the same time as a wrong password. Without it, response timing tells an
# attacker which login ids are real — which is the same leak that 세션_보관_정책.md 1.2절
# closes by refusing to distinguish the two failures in the response body.
_DUMMY_HASH = _hasher.hash("timing-equaliser")


@dataclass(frozen=True)
class Account:
    """A user as stored. Note what is absent: no email, no display name.

    Every field here is one more thing we hold about a person (도메인_모델.md 2.1절).
    """

    user_id: str
    login_id: str
    password_hash: str
    created_at: str


def seed(connection: sqlite3.Connection, seeds: list[SeedAccount]) -> int:
    """Make the configured accounts exist. Returns how many were inserted or updated.

    ⚠️ Matched on `login_id`, and an existing row keeps its `user_id`. Sessions reference
    `user_id` and access control compares it to the requester (INV-9), so re-issuing one
    on restart would orphan every session that user owns — the failure would look like
    "my work disappeared", not like a configuration bug.

    A changed hash in .env does update the row: that is how a password is rotated when
    there is no password-change endpoint.
    """
    if not seeds:
        return 0

    now = datetime.now(UTC).isoformat()
    for account in seeds:
        connection.execute(
            """
            INSERT INTO users (user_id, login_id, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(login_id) DO UPDATE SET password_hash = excluded.password_hash
            """,
            (str(uuid.uuid4()), account.login_id, account.password_hash, now),
        )
    connection.commit()
    return len(seeds)


_SELECT = "SELECT user_id, login_id, password_hash, created_at FROM users"


def find_by_login_id(connection: sqlite3.Connection, login_id: str) -> Account | None:
    """By the id a person types. Used at login, and to keep `user_id` stable across seeds."""
    row = connection.execute(f"{_SELECT} WHERE login_id = ?", (login_id,)).fetchone()
    return None if row is None else Account(**dict(row))


def find_by_user_id(connection: sqlite3.Connection, user_id: str) -> Account | None:
    """By the id other data references. Used to resolve a session token to its owner.

    ⚠️ A signed token proves the `user_id` came from us; it does not prove the account still
    exists. Accounts come from `ADGEN_ACCOUNTS` and can be removed from it, and a stateless
    token has no way to learn that (ADR-0013) — so this lookup is what closes the gap, and
    `None` here has to end as a 401 rather than as a logged-in nobody.
    """
    row = connection.execute(f"{_SELECT} WHERE user_id = ?", (user_id,)).fetchone()
    return None if row is None else Account(**dict(row))


def authenticate(connection: sqlite3.Connection, login_id: str, password: str) -> Account | None:
    """Return the account when the credentials match, `None` otherwise.

    One return value for both failures on purpose. The caller cannot tell "no such login
    id" from "wrong password" and so cannot leak the difference — 세션_보관_정책.md 1.2절
    requires the response not to distinguish them, and a caller that never learns the
    difference cannot forget.

    ⚠️ Never log `password`, and never put it in an exception message. A debug log of the
    whole request body is the most common way plaintext passwords end up on disk.
    """
    account = find_by_login_id(connection, login_id)

    try:
        _hasher.verify(_DUMMY_HASH if account is None else account.password_hash, password)
    except Argon2Error:
        return None

    # The dummy hash can only be "verified" by the dummy password, which is not reachable
    # from user input — but returning the account here would be a login without a user.
    return account

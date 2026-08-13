"""Account seeding and password checking.

The two behaviours worth protecting here are not "does a correct password work" but:

- a restart must not change `user_id` (sessions reference it — INV-9), and
- a failed login must not reveal whether the login id exists (세션_보관_정책.md 1.2절).

⚠️ `test_inv9_...` carries the invariant id in its *name*, not only in a docstring
(도메인_모델.md 7.1절): whoever later deletes it should find out from `grep INV-9` that it
was holding up an invariant. This is not the INV-9 test itself — that one checks that
another user's session 404s, and it arrives with the session routes — but the ownership
check is worthless if `user_id` moves under it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from backend_core.accounts import authenticate, find_by_login_id, seed
from backend_core.config import SeedAccount
from backend_core.storage import connect, init_schema

# Named for the account they belong to, not "password": ruff (S105) flags a literal
# assigned to a password-shaped name, and suppressing that rule repo-wide is worse.
PLAINTEXT_DEMO1 = "correct-horse-battery-staple"
PLAINTEXT_DEMO2 = "not-the-one"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A real SQLite file, not `:memory:`.

    The behaviour under test is what survives a restart, and an in-memory database cannot
    show that. ADR-0010 promised that tests isolate to one temporary directory — this is
    that promise being kept.
    """
    with connect(tmp_path / "test.sqlite") as connection:
        init_schema(connection)
        yield connection


@pytest.fixture
def seeds() -> list[SeedAccount]:
    """Two accounts, because one cannot prove INV-9 (ADR-0008)."""
    hasher = PasswordHasher()
    return [
        SeedAccount(login_id="demo1", password_hash=hasher.hash(PLAINTEXT_DEMO1)),
        SeedAccount(login_id="demo2", password_hash=hasher.hash(PLAINTEXT_DEMO2)),
    ]


def test_init_schema_is_idempotent(tmp_path: Path) -> None:
    """Startup runs it every time (ADR-0011: no separate migration step in the deploy)."""
    with connect(tmp_path / "twice.sqlite") as connection:
        init_schema(connection)
        init_schema(connection)


def test_seed_creates_the_configured_accounts(
    db: sqlite3.Connection, seeds: list[SeedAccount]
) -> None:
    assert seed(db, seeds) == 2
    assert find_by_login_id(db, "demo1") is not None
    assert find_by_login_id(db, "demo2") is not None


def test_inv9_reseeding_keeps_the_same_user_id(
    db: sqlite3.Connection, seeds: list[SeedAccount]
) -> None:
    """INV-9 depends on this.

    Seeding runs on every startup. If it re-issued `user_id`, every session that user owns
    would stop matching its owner after a restart and would 404 — which reaches the user
    as "my work disappeared", not as a configuration problem.
    """
    seed(db, seeds)
    before = find_by_login_id(db, "demo1")

    seed(db, seeds)
    after = find_by_login_id(db, "demo1")

    assert before is not None and after is not None
    assert before.user_id == after.user_id


def test_reseeding_updates_a_rotated_hash(db: sqlite3.Connection) -> None:
    """With no password-change endpoint (ADR-0008), editing infra/.env is the only way to
    rotate a password. The row has to follow."""
    hasher = PasswordHasher()
    seed(db, [SeedAccount(login_id="demo1", password_hash=hasher.hash(PLAINTEXT_DEMO1))])
    seed(db, [SeedAccount(login_id="demo1", password_hash=hasher.hash(PLAINTEXT_DEMO2))])

    assert authenticate(db, "demo1", PLAINTEXT_DEMO1) is None
    assert authenticate(db, "demo1", PLAINTEXT_DEMO2) is not None


def test_authenticate_accepts_the_right_password(
    db: sqlite3.Connection, seeds: list[SeedAccount]
) -> None:
    seed(db, seeds)
    account = authenticate(db, "demo1", PLAINTEXT_DEMO1)

    assert account is not None
    assert account.login_id == "demo1"


def test_authenticate_rejects_another_accounts_password(
    db: sqlite3.Connection, seeds: list[SeedAccount]
) -> None:
    """Both directions, because a lookup that ignored `login_id` would still pass one of
    them: demo2's password must not open demo1, and vice versa."""
    seed(db, seeds)
    assert authenticate(db, "demo1", PLAINTEXT_DEMO2) is None
    assert authenticate(db, "demo2", PLAINTEXT_DEMO1) is None


def test_authenticate_rejects_an_unknown_login_id_the_same_way(
    db: sqlite3.Connection, seeds: list[SeedAccount]
) -> None:
    """Both failures return `None`, so a caller cannot tell them apart and therefore
    cannot leak the difference (세션_보관_정책.md 1.2절)."""
    seed(db, seeds)
    assert authenticate(db, "no-such-user", PLAINTEXT_DEMO1) is None

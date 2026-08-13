"""Session token issuing and verification.

What is worth protecting here is not "does a token round-trip" but the properties ADR-0013
bought and paid for: a forged token must not pass, an expired one must not pass, and the
absence of a signing key must stop the process instead of quietly signing with nothing.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from backend_core.tokens import (
    SigningKeyMissingError,
    _encode,
    _sign,
    issue,
    require_secret,
    verify,
)

SECRET = "test-signing-key"  # noqa: S105 - a test fixture, not a credential
OTHER_SECRET = "a-different-signing-key"  # noqa: S105 - same
USER_ID = "3f2b1c00-0000-4000-8000-000000000001"
ONE_DAY_S = 86400


def test_a_freshly_issued_token_names_its_user() -> None:
    assert verify(issue(USER_ID, SECRET, ONE_DAY_S), SECRET) == USER_ID


def test_a_token_signed_with_another_key_is_rejected() -> None:
    """The signature is the only thing standing between a cookie and someone else's
    account — the payload itself is plain text (see below)."""
    assert verify(issue(USER_ID, OTHER_SECRET, ONE_DAY_S), SECRET) is None


def test_a_tampered_payload_is_rejected() -> None:
    """Swapping in another `userId` while keeping the signature must not work. This is the
    attack the signature exists for, so it gets its own test rather than being implied by
    the wrong-key case."""
    token = issue(USER_ID, SECRET, ONE_DAY_S)
    _, _, signature = token.partition(".")
    forged_payload = base64.urlsafe_b64encode(b"someone-else:99999999999").rstrip(b"=").decode()

    assert verify(f"{forged_payload}.{signature}", SECRET) is None


def test_an_expired_token_is_rejected() -> None:
    """24h fixed with no refresh (세션_보관_정책.md 1.4절), so expiry is the only thing
    that ever ends a session — logout just clears the cookie (ADR-0013)."""
    issued_at = datetime.now(UTC) - timedelta(seconds=ONE_DAY_S + 1)

    assert verify(issue(USER_ID, SECRET, ONE_DAY_S, now=issued_at), SECRET) is None


def test_a_token_valid_a_moment_before_expiry_still_works() -> None:
    """Pairs with the test above: without it, a `verify` that rejected everything would
    pass the expiry test for the wrong reason."""
    issued_at = datetime.now(UTC) - timedelta(seconds=ONE_DAY_S - 60)

    assert verify(issue(USER_ID, SECRET, ONE_DAY_S, now=issued_at), SECRET) == USER_ID


@pytest.mark.parametrize(
    "token",
    ["", "no-separator-at-all", ".", "not-base64.also-not-base64"],
    ids=["empty", "no separator", "empty parts", "unparseable"],
)
def test_malformed_tokens_are_rejected_the_same_way(token: str) -> None:
    """A cookie is attacker-controlled input. Every shape of nonsense has to come back as
    `None` — the same answer as expired and forged, because the contract has one code for
    all of them (401 `UNAUTHORIZED`, API_계약.md 6절)."""
    assert verify(token, SECRET) is None


def test_a_correctly_signed_payload_in_the_wrong_format_is_rejected() -> None:
    """Reaches the branch the cases above cannot: the signature checks out, so this token
    really was signed with our key, but the payload is not `userId:expiry`. That means the
    key is shared with something signing a different format, and trusting the contents
    would be trusting that other thing. Uses the private signer deliberately — no public
    call can produce this shape, which is the point."""
    payload = _encode("no-colon-here")

    assert verify(f"{payload}.{_sign(payload, SECRET)}", SECRET) is None


def test_the_payload_is_readable_by_anyone_holding_the_token() -> None:
    """Not a bug — ADR-0013 records it, and this test is here so the property is visible
    to whoever later considers putting something else in the payload. Signing prevents
    forgery; it does not hide. Hence `userId` and an expiry, and nothing personal."""
    payload, _, _ = issue(USER_ID, SECRET, ONE_DAY_S).partition(".")
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()

    assert decoded.startswith(f"{USER_ID}:")


def test_signing_without_a_key_fails_loudly() -> None:
    """ADR-0013 refuses to default the key: a committed default is a published one. So the
    absence has to raise rather than produce a token anyone can forge."""
    with pytest.raises(SigningKeyMissingError):
        issue(USER_ID, "", ONE_DAY_S)

    with pytest.raises(SigningKeyMissingError):
        require_secret("")


def test_verifying_without_a_key_rejects_rather_than_raising() -> None:
    """The other direction is not symmetric, on purpose.

    Issuing without a key must raise — a token nobody can trust is worse than no token. But
    *verifying* without one is just a failed verification: with no key nothing can be a
    valid token, so `None` is the honest answer, and raising turned a cookie sent at a
    half-configured server into a 500 (tests/api/test_startup.py).

    ⚠️ What it must never do is verify with the empty key. That would accept anything an
    attacker signs with the same emptiness, which is why this returns `None` even for a
    token whose signature "matches" under an empty secret.
    """
    forged_under_empty_key = f"{_encode(f'{USER_ID}:99999999999')}."
    forged_under_empty_key += _sign(forged_under_empty_key[:-1], "")

    assert verify("anything", "") is None
    assert verify(forged_under_empty_key, "") is None

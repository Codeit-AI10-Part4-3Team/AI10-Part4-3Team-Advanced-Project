"""Session tokens: issue one, and check one.

ADR-0013 chose a *signed stateless* token — `userId` plus an expiry, signed with a server
secret — over an opaque token stored in SQLite. Three consequences of that decision are
visible in this module, and none of them are accidents:

- **Verification touches no storage.** That is the whole point: with a single worker
  (ADR-0011) every request pays for the auth check, and a SQLite read is blocking I/O
  (API_계약.md 2.2절).
- **There is no revoke.** A token that has leaked stays valid until it expires, and
  logging out only clears the cookie. Read ADR-0013 before adding a deny list — this is
  the decision's price, not a bug someone forgot to fix.
- **The payload is readable.** Signing prevents forgery, it does not hide anything, so
  only `userId` and the expiry go in. No personal data (ADR-0013).

ADR-0013 left the library choice to this PR. It is the standard library: HMAC-SHA256 over
two fields, compared with `hmac.compare_digest`. A JWT library would add a runtime
dependency and an algorithm field we would then have to pin against `alg: none` confusion,
to carry a payload with no claims we use. The narrower thing has less to get wrong.

⚠️ FastAPI-free by design, like the rest of backend_core.
"""

from __future__ import annotations

import base64
import hmac
from datetime import UTC, datetime
from hashlib import sha256

# `.` separates the payload from its signature; `:` separates the fields inside the
# payload. Both are cookie-safe, and neither appears in base64url output.
_PART_SEPARATOR = "."
_FIELD_SEPARATOR = ":"


class SigningKeyMissingError(RuntimeError):
    """Raised when a token operation is attempted with no signing key configured."""


def require_secret(secret: str) -> None:
    """Fail loudly when the signing key is missing.

    ADR-0013 refuses to give the key a default: a committed default is a published signing
    key, and one that works is one nobody notices in production. So the absence has to stop
    something — this function is what the startup wiring calls to make it stop the process
    rather than the first login.
    """
    if not secret:
        raise SigningKeyMissingError(
            "ADGEN_SESSION_SECRET is empty. A signing key has no default on purpose "
            "(ADR-0013) — generate one and put it in infra/.env: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )


def issue(user_id: str, secret: str, max_age_s: int, now: datetime | None = None) -> str:
    """Sign `user_id` with an expiry `max_age_s` seconds out.

    The lifetime is passed in rather than read here because it is a setting
    (ADR-0013, API_계약.md 6절) and because a test that has to wait 24 hours is not a test.
    """
    require_secret(secret)

    expires_at = int((now or datetime.now(UTC)).timestamp()) + max_age_s
    payload = _encode(f"{user_id}{_FIELD_SEPARATOR}{expires_at}")
    return f"{payload}{_PART_SEPARATOR}{_sign(payload, secret)}"


def verify(token: str, secret: str, now: datetime | None = None) -> str | None:
    """Return the `user_id` the token carries, or `None` if it does not hold up.

    ⚠️ One `None` for every kind of failure — malformed, forged, expired. The contract has
    a single code for all of them (401 `UNAUTHORIZED`, API_계약.md 6절), and a caller that
    never learns which one it was cannot leak the difference by accident.

    "No signing key configured" is one of those failures, not an error. With no key nothing
    can be a valid token, so the honest answer is `None` — and it must never be "verify with
    an empty key", which would accept anything an attacker signs with the same emptiness.
    Raising instead would turn a cookie sent at a half-configured server into a 500
    (2026-08-13 실측 on a fresh clone). The operator-facing signal for a missing key is the
    startup check, which is where ADR-0013 puts it.
    """
    if not secret:
        return None

    payload, separator, signature = token.partition(_PART_SEPARATOR)
    if not separator:
        return None

    # compare_digest, not `==`: an early-exit comparison leaks how many leading bytes of a
    # guessed signature were right, which is enough to build one byte at a time.
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        return None

    try:
        user_id, _, expires_at = _decode(payload).rpartition(_FIELD_SEPARATOR)
        expiry = int(expires_at)
    except (ValueError, UnicodeDecodeError):
        # Signed, so this is our own token — but a signature that checks out on garbage
        # means the key is shared with something that signs a different format.
        return None

    if not user_id or int((now or datetime.now(UTC)).timestamp()) >= expiry:
        return None
    return user_id


def _sign(payload: str, secret: str) -> str:
    return _encode_bytes(hmac.new(secret.encode(), payload.encode(), sha256).digest())


def _encode(value: str) -> str:
    return _encode_bytes(value.encode())


def _encode_bytes(value: bytes) -> str:
    # Padding stripped: `=` is legal in a cookie value but needs quoting, and quoting is
    # one more thing for a client to get wrong.
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode()

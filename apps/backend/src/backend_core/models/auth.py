"""Auth wire models — the login request, and who the caller is.

Contract: packages/contracts/openapi.yaml, the `auth` tag. Both schemas are notable for
what they leave out.

`LoginRequest` carries the only plaintext password in the system, and it exists only on
the way in: what gets stored is a hash, and nothing sends it back. ⚠️ Never log a request
body on this route — a debug log of the whole body is the most common way plaintext
passwords end up on disk (세션_보관_정책.md 1.2절).

`Me` has no email and no display name. The contract says so explicitly, and the reason is
that an email is one more personal item we would then have to hold, protect and delete
(도메인_모델.md 2.1절). `userId` is what other data references; `loginId` is what the
person types and may change.

⚠️ Contract first: edit `openapi.yaml`, then this file (AGENTS.md). The conformance tests
in tests/backend_core/models/test_auth.py compare the two field by field.
"""

from datetime import datetime

from pydantic import Field

from backend_core.models.common import Base


class LoginRequest(Base):
    """Contract: `components.schemas.LoginRequest`."""

    login_id: str = Field(min_length=1, max_length=64)

    # No max length. A cap here is a cap on password strength, and the value never reaches
    # storage as-is — argon2 hashes it to a fixed size (세션_보관_정책.md 1.2절).
    password: str = Field(min_length=1)


class Me(Base):
    """Contract: `components.schemas.Me`. Returned by login and by `GET /v1/me`.

    Deliberately the same shape from both routes: a client that has just logged in and one
    that is restoring a session should not have to tell the two apart.
    """

    user_id: str
    login_id: str
    created_at: datetime

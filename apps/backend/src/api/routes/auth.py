"""Auth routes: log in, log out, and the three that answer 501.

Contract: packages/contracts/openapi.yaml, the `auth` tag.

The 501s are not placeholders someone forgot to fill in. ADR-0008 decided that the walking
skeleton checks fixed accounts and does not create them: the question the skeleton has to
answer is "does authentication actually sit on the end-to-end path", and creating accounts
does not answer it. They are in the contract because the screens need to know the shape
they will eventually call.

⚠️ Routes stay thin — validate, call the domain, map the response (apps/backend/AGENTS.md).
The password never leaves this module's stack frame, and nothing here logs the request body
(세션_보관_정책.md 1.2절).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Annotated, Literal, TypedDict

from fastapi import APIRouter, Depends, Response, status

from api import deps
from api.errors import invalid_credentials, not_implemented
from backend_core import tokens
from backend_core.accounts import Account, authenticate
from backend_core.config import SESSION_COOKIE_NAME, Settings
from backend_core.models import LoginRequest, Me

router = APIRouter(prefix="/v1", tags=["auth"])


class _CookieAttrs(TypedDict):
    httponly: bool
    secure: bool
    samesite: Literal["lax"]
    path: str


# Contract: `session_token=<token>; HttpOnly; Secure; SameSite=Lax`.
#
# - HttpOnly  — scripts cannot read it, so one XSS does not hand over the session. This is
#               why the token is not kept in localStorage (API_계약.md 6절).
# - Secure    — see the warning below.
# - SameSite  — Lax, not Strict. Strict also withholds the cookie on a plain link into the
#               app, so a logged-in user arriving from anywhere else would look logged out.
#
# Set and cleared through one constant so the two cannot drift: a browser only deletes a
# cookie when the clearing `Set-Cookie` matches the attributes that created it, and a logout
# that silently fails to clear is worse than no logout at all.
#
# ⚠️ `Secure` is not configurable, deliberately. HTTPS termination is still undecided
# (API_계약.md 2절 — 소관 05, 기한 배포 전) and the current stack has no proxy, so a knob to
# switch this off would be switched off "just for now" and then deployed. Login sends a
# password (ADR-0008), so the order is HTTPS first, deploy second. Local development is
# unaffected: browsers treat `http://localhost` as a trustworthy origin.
_COOKIE_ATTRS: _CookieAttrs = {
    "httponly": True,
    "secure": True,
    "samesite": "lax",
    "path": "/",
}


def _me(account: Account) -> Me:
    """Note what is not carried across: `password_hash` has no field on `Me` to land in.

    `created_at` is parsed here rather than left to pydantic's string coercion. The stored
    value is whatever `accounts.seed` wrote, and the contract promises `format: date-time` —
    converting at the boundary means a malformed row fails here, with the row in hand,
    instead of somewhere downstream.
    """
    return Me(
        user_id=account.user_id,
        login_id=account.login_id,
        created_at=datetime.fromisoformat(account.created_at),
    )


@router.post("/auth/login", response_model=Me)
def login(
    body: LoginRequest,
    response: Response,
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    settings: Annotated[Settings, Depends(deps.settings)],
) -> Me:
    """Check the credentials, then set the session cookie.

    ⚠️ `authenticate` answers `None` to "no such login id" and to "wrong password" alike,
    and this route has to keep them together: naming which half was wrong tells an attacker
    which login ids exist (세션_보관_정책.md 1.2절).
    """
    # Not behind `current_user`, so the header is set here too. This response carries the
    # session token in `Set-Cookie`; a shared cache that stored it would hand one person's
    # session to the next caller.
    response.headers["Cache-Control"] = "no-store"

    account = authenticate(connection, body.login_id, body.password)
    if account is None:
        invalid_credentials()

    token = tokens.issue(account.user_id, settings.session_secret, settings.session_max_age_s)
    response.set_cookie(
        SESSION_COOKIE_NAME, token, max_age=settings.session_max_age_s, **_COOKIE_ATTRS
    )
    return _me(account)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, _: Annotated[Account, Depends(deps.current_user)]) -> None:
    """Clear the cookie. That is the whole of it.

    ⚠️ The token stays valid on the server for the rest of its 24 hours — there is no deny
    list, by decision (ADR-0013). Read that ADR before "fixing" this: the absence is what
    keeps the auth check free of storage I/O, not an oversight.

    Requires a valid session because the contract documents a 401 here. A logout that
    answered 204 to anyone would be a route that does nothing, reachable by everyone.
    """
    response.delete_cookie(SESSION_COOKIE_NAME, **_COOKIE_ATTRS)


@router.post("/auth/signup", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def signup() -> None:
    not_implemented("가입은 제공하지 않습니다. 미리 만들어 둔 고정 계정만 씁니다 (ADR-0008).")


@router.get("/me", response_model=Me)
def me(account: Annotated[Account, Depends(deps.current_user)]) -> Me:
    """Who the cookie says you are — read back from storage, not from the cookie.

    The token carries a `userId` and nothing else (ADR-0013), so the row is the only place
    `loginId` and `createdAt` can come from.
    """
    return _me(account)


@router.delete("/me", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def withdraw() -> None:
    not_implemented("탈퇴는 제공하지 않습니다 (ADR-0008).")


@router.patch("/me/password", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def change_password() -> None:
    not_implemented(
        "비밀번호 변경과 재설정은 제공하지 않습니다. 메일 발송 경로가 없습니다 "
        "(ADR-0008, 세션_보관_정책.md 1.2절)."
    )

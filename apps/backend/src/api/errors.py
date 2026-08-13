"""Contract-shaped error responses.

The contract specifies `{code, message}` with a fixed code enum, not FastAPI's default
`{"detail": ...}`. Clients branch on `code`, so it has to survive all the way to the wire.
"""

from typing import NoReturn

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend_core.models import Error, ErrorCode


class ApiError(HTTPException):
    """HTTPException carrying a contract error code."""

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code: ErrorCode = code


def not_found(message: str = "찾을 수 없습니다.") -> NoReturn:
    raise ApiError(404, "NOT_FOUND", message)


def unauthorized(message: str = "로그인이 필요합니다.") -> NoReturn:
    """No token, or one that did not hold up.

    ⚠️ One message for missing, forged and expired alike. The token layer already refuses
    to tell them apart (backend_core/tokens.verify), and re-introducing the distinction
    here would undo that at the last step.
    """
    raise ApiError(401, "UNAUTHORIZED", message)


def invalid_credentials(message: str = "아이디 또는 비밀번호가 올바르지 않습니다.") -> NoReturn:
    """Login failed. **Never say which half was wrong** (세션_보관_정책.md 1.2절).

    "No such account" and "wrong password" are the same answer here, because the difference
    tells an attacker which login ids exist. The message says "아이디 또는" for the same
    reason: a message that named one of them would leak what the code carefully does not.
    """
    raise ApiError(401, "INVALID_CREDENTIALS", message)


def not_implemented(message: str = "이 기능은 제공하지 않습니다.") -> NoReturn:
    """Signup, withdrawal and password change (ADR-0008).

    501 rather than 404 because 404 is indistinguishable from a typo in the path, and
    rather than 200 because a 200 makes an undone thing look done.
    """
    raise ApiError(501, "NOT_IMPLEMENTED", message)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render ApiError (and any other HTTPException) in the contract's error shape."""
    if isinstance(exc, ApiError):
        status, code, message = exc.status_code, exc.code, str(exc.detail)
    elif isinstance(exc, StarletteHTTPException):
        # Covers FastAPI's HTTPException (a subclass) and the router's own 404/405.
        status, code, message = exc.status_code, _code_for(exc.status_code), str(exc.detail)
    else:  # pragma: no cover - defensive; FastAPI routes non-HTTP errors elsewhere
        status, code, message = 500, "INTERNAL", "내부 오류가 발생했습니다."
    return JSONResponse(
        status_code=status,
        content=Error(code=code, message=message).model_dump(by_alias=True),
        # Error bodies can echo request context; keep them out of shared caches.
        headers={"Cache-Control": "no-store"},
    )


def _code_for(status_code: int) -> ErrorCode:
    """Fallback for HTTPExceptions raised without a contract code.

    Mostly Starlette's own — the router's 404/405, and the 401 that a security dependency
    raises before our code runs. Routes we write should raise the helpers above instead, so
    that the code is chosen on purpose rather than inferred from a number.
    """
    if status_code == 401:
        return "UNAUTHORIZED"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code == 501:
        return "NOT_IMPLEMENTED"
    if status_code == 503:
        return "UPSTREAM_UNAVAILABLE"
    if 400 <= status_code < 500:
        return "INVALID_REQUEST"
    return "INTERNAL"

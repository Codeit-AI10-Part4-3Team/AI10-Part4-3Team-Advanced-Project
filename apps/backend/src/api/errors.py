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


def state_conflict(message: str) -> NoReturn:
    """The session is not at a point where this request means anything (INV-2, INV-3, INV-7).

    409 rather than 422: the request itself is well-formed, and the same body would have
    worked a moment earlier or will work a moment later. A 422 would send the client looking
    for a mistake in what it sent.
    """
    raise ApiError(409, "STATE_CONFLICT", message)


def invalid_image(message: str) -> NoReturn:
    """The upload is not an image we accept (422 `INVALID_IMAGE`).

    ⚠️ Refused, never silently converted or cropped. The picture is the product (기획서 5.2),
    and a server that quietly re-encodes it changes what the user submitted.
    """
    raise ApiError(422, "INVALID_IMAGE", message)


def upstream_unavailable(message: str = "생성 엔진을 사용할 수 없습니다.") -> NoReturn:
    """The engine could not be reached, on a seam with no fallback.

    ⚠️ Only `brief:fill` degrades (ADR-0005). Draft generation and rendering fail loudly,
    because there is no pre-approved answer for a draft — the copy differs per product, so
    "something reasonable" cannot exist in advance. Adding a fallback here would mean
    inventing ad copy, which is the one thing the whole design forbids.
    """
    raise ApiError(503, "UPSTREAM_UNAVAILABLE", message)


def generation_timeout(message: str = "생성이 제한 시간을 넘겼습니다.") -> NoReturn:
    """The engine answered too late (504). Distinct from a 503 so a client can decide
    whether retrying is sensible — it is here, and it is not for an outage."""
    raise ApiError(504, "GENERATION_TIMEOUT", message)


def content_policy_rejected(message: str) -> NoReturn:
    """The engine declined rather than invent an unsupported claim (422).

    ⚠️ Not a bug and not something to retry around. The guardrail refusing is the design
    working (INV-6, ADR-0007); a retry loop here would keep asking until the model produced
    something that slipped through, which is the failure mode the guardrail exists for.
    """
    raise ApiError(422, "CONTENT_POLICY_REJECTED", message)


def invalid_request(message: str) -> NoReturn:
    """Well-formed but not allowed — a patch naming a field that is not patchable, most of
    all (INV-4, INV-8)."""
    raise ApiError(422, "INVALID_REQUEST", message)


def not_implemented(message: str = "이 기능은 제공하지 않습니다.") -> NoReturn:
    """Signup, withdrawal and password change (ADR-0008).

    501 rather than 404 because 404 is indistinguishable from a typo in the path, and
    rather than 200 because a 200 makes an undone thing look done.
    """
    raise ApiError(501, "NOT_IMPLEMENTED", message)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render pydantic's request-validation failures in the contract's error shape.

    ⚠️ Without this, **the most common error in the API** answers with FastAPI's default
    `{"detail": [...]}` — a 422 with no `code` at all (2026-08-14 실측: `POST /v1/auth/login`
    with no `password`). Everything else in this module exists so that clients can branch on
    `code`, and the one path they hit most often was the one that never carried it.

    It also invalidated a claim made elsewhere: `models/patch.py` says naming `adPlan` is
    "a 422 `INVALID_REQUEST` — the contract's answer". It was a 422 with a different body.
    The tests missed it because they asserted the status and never the body.

    ⚠️ The detail is **summarised, not forwarded.** pydantic's list embeds the offending
    input, and on `POST /v1/auth/login` that input is a plaintext password — echoing it into
    a response body (and any log that records bodies) is exactly what 세션_보관_정책 1.2절
    forbids.
    """
    fields = _offending_fields(exc)
    message = "요청 형식이 올바르지 않습니다."
    if fields:
        message = f"{message} 확인이 필요한 항목: {', '.join(fields)}."
    return JSONResponse(
        status_code=422,
        content=Error(code="INVALID_REQUEST", message=message).model_dump(by_alias=True),
        headers={"Cache-Control": "no-store"},
    )


def _offending_fields(exc: Exception) -> list[str]:
    """Field names only — never values. See the warning in the handler above."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):  # pragma: no cover - defensive
        return []
    names = []
    for error in errors():
        location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query")]
        if location:
            names.append(".".join(location))
    return names


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
    if status_code == 409:
        return "STATE_CONFLICT"
    if status_code == 504:
        return "GENERATION_TIMEOUT"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code == 501:
        return "NOT_IMPLEMENTED"
    if status_code == 503:
        return "UPSTREAM_UNAVAILABLE"
    if 400 <= status_code < 500:
        return "INVALID_REQUEST"
    return "INTERNAL"

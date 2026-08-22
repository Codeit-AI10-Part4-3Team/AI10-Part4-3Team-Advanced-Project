"""FastAPI entrypoint.

Keep routers thin: request validation -> backend_core call -> response mapping.
Business logic belongs in backend_core, which must stay importable without FastAPI.

Contract: packages/contracts/openapi.yaml — both the paths served here and the paths this
app calls on apps/ai-engine.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from api import deps, sweeper, worker
from api.errors import api_error_handler, unhandled_error_handler, validation_error_handler
from api.routes import auth, catalog, jobs, sessions
from backend_core.accounts import count as account_count
from backend_core.accounts import seed
from backend_core.observability import install_file_log
from backend_core.storage import connect, init_schema
from backend_core.tokens import require_secret

ART_STYLE_CACHE_CONTROL = "public, max-age=3600"
"""화풍 예시에 붙는 캐시 헤더.

⚠️ `images.CACHE_CONTROL` 이 `private` 인 것과 갈립니다. 그쪽은 업로드 사진과 생성 결과라
공유 캐시에 두면 안 되지만, 이 여덟 장은 우리가 만든 제품 자산이고 로그인 없이 열려 있습니다.

한 시간인 것은 **같은 이름으로 다시 전달되는 경우** 때문입니다. 파일 이름은 조건이 바뀔 때만
바뀌므로(`style-01-traits.webp`), 같은 조건으로 다시 뽑은 그림은 이름이 같고 내용만 다릅니다.
길게 잡으면 사용자가 옛 예시를 보는 동안 실제 결과는 새 그림으로 나옵니다 - 예시와 결과가
어긋나는 것이 A-3 이 막으려던 바로 그것입니다. 여덟 장 합쳐 1MB 라 짧게 잡아도 부담이 없어
파일명에 해시를 붙이지 않았습니다 (PR #194, 05).
"""


class _ArtStyleFiles(StaticFiles):
    """`StaticFiles` 에 두 가지만 얹습니다 - 캐시 헤더, 그리고 요청 시점의 디렉토리.

    ⚠️ `StaticFiles` 는 `Cache-Control` 을 붙이지 않고 `ETag` 와 `Last-Modified` 만 보냅니다.
    그러면 브라우저가 매번 조건부 요청을 보내거나(느림) 자기 휴리스틱으로 캐시합니다(예측
    불가). 어느 쪽도 위 상수가 정하려는 것이 아닙니다.

    ⚠️ **디렉토리를 import 시점이 아니라 요청 시점에 읽습니다.** 마운트는 모듈이 로드될 때
    한 번 만들어지므로, 생성자에 경로를 박으면 그 뒤에 바뀐 설정이 반영되지 않습니다. 배포는
    프로세스를 새로 띄우니 차이가 없지만, **이 앱의 다른 모든 설정 읽기와 모양이 달라집니다**
    - 시험은 `deps.settings.cache_clear()` 로 값을 갈아 끼우는데 이 마운트만 그 규칙 밖에
    있게 되고, 그러면 마운트 동작을 시험으로 고정할 방법이 없습니다. `deps.settings` 는
    캐시되므로 요청마다 다시 읽어도 비용이 없습니다.
    """

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        # ⚠️ `directory` 가 아니라 `all_directories` 를 갱신합니다 - `lookup_path` 가 도는
        #    것이 그쪽입니다(starlette 1.6). `directory` 만 바꾸면 조회는 생성자 값을 계속
        #    쓰고, 증상은 오류가 아니라 **전부 404** 입니다. `get_directories` 를 거치는
        #    것은 그 목록을 만드는 규칙(패키지 자산 포함)을 여기서 다시 구현하지 않기
        #    위해서입니다.
        self.directory = deps.settings().art_style_dir
        self.all_directories = self.get_directories(self.directory, self.packages)
        return super().lookup_path(path)

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = ART_STYLE_CACHE_CONTROL
        return response


def _check_art_style_dir(settings: Any) -> None:
    """화풍 디렉토리가 상태 파일을 함께 열어 주지 않는지 확인합니다. 어기면 기동하지 않습니다.

    ⚠️ **이 검사가 없으면 오타 하나가 사용자 데이터를 인증 없이 공개합니다.**
    `ADGEN_ART_STYLE_DIR=/data` 로 한 글자 줄이면 `/static/art-styles/adgen.sqlite` 가
    계정 해시와 세션이 든 파일을 그대로 내려줍니다. 마운트가 인증 밖이라 아무도 막지
    않고, 증상도 없습니다 - 아무도 그 URL 을 시도하지 않는 동안은 정상으로 보입니다.

    ⚠️ **뜨지 않는 쪽을 골랐습니다.** 이 저장소의 기본 방침은 "측정을 잃더라도 배포는
    살린다" 이지만(observability), 여기서는 반대입니다. 계속 뜨는 것이 곧 데이터를 계속
    노출하는 것이고, 기동 실패는 배포하는 사람이 즉시 봅니다.
    """
    art = Path(settings.art_style_dir).resolve()
    for name, other in (
        ("db_path", Path(settings.db_path).resolve().parent),
        ("image_dir", Path(settings.image_dir).resolve()),
    ):
        if art == other or art in other.parents:
            raise RuntimeError(
                f"ADGEN_ART_STYLE_DIR({art}) 이 {name}({other}) 을 포함합니다. "
                "이 경로는 인증 없이 열리므로 상태 파일과 같은 디렉토리를 가리킬 수 없습니다."
            )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Make the database usable before the first request reaches it.

    The tables are created and the fixed accounts are seeded on every startup. There is no
    separate migration step to hang this off: deployment is `git pull` + `docker compose up`
    (ADR-0011), so anything that must happen before serving has to happen here.

    Seeding runs every time on purpose — it is an upsert that keeps `user_id` (accounts.py),
    which is how a rotated hash in infra/.env reaches the row when there is no
    password-change endpoint (ADR-0008).
    """
    settings = deps.settings()

    # ⚠️ Before anything else, so a failure during startup is in the record too. The
    # container's own stdout does not survive the next `compose up --build` (ADR-0011 makes
    # deployment a rebuild), and a crash loop is exactly when someone needs yesterday's lines
    # (backend_core.observability).
    install_file_log(settings.log_dir, settings.log_retention_d)

    # 인증 밖에 열리는 경로가 상태 파일을 함께 내주지 않는지. 어기면 여기서 멈춥니다.
    _check_art_style_dir(settings)

    with connect(settings.db_path) as connection:
        init_schema(connection)
        seed(connection, settings.accounts)

        # ADR-0013 says a missing signing key must stop the process, not the first login.
        #
        # ⚠️ The condition is **how many accounts are in the database**, not how many are
        # configured, and the difference is the whole point. `ADGEN_ACCOUNTS` says what this
        # startup was told to seed; the file says what is actually there. With a named volume
        # (ADR-0014) they come apart the first time someone restarts without their .env:
        # `seed([])` does not delete anything, so a real account survives, `authenticate`
        # succeeds against it, and `tokens.issue` then raises on the empty key — a 500 on a
        # correct password, which is exactly the failure this check exists to prevent
        # (2026-08-14, PR #84 리뷰에서 신호정 발견).
        #
        # An empty database still starts with no key: a fresh clone has to serve /health,
        # because a stack that needs configuration before it starts cannot be deployed empty
        # (config.py).
        if account_count(connection):
            require_secret(settings.session_secret)

        # ⚠️ Before the worker starts, not after. A job left `running` by a crash or a
        # deploy is a session stuck in `rendering` for ever, because `rendering` has no edge
        # back and nothing would ever pick that job up again (ADR-0015).
        worker.requeue_interrupted(connection)

    # ⚠️ Two background tasks, nested rather than merged. They have nothing to say to each
    # other and different failure modes: a stalled render leaves a spinner, a stalled sweep
    # leaves personal data past its period (세션_보관_정책 2절). Keeping them separate means
    # turning one off for a test does not turn off the other.
    async with (
        worker.lifespan_task(_app, settings.worker_poll_interval_s, settings.worker_enabled),
        sweeper.lifespan_task(settings),
    ):
        yield


# ⚠️ `redirect_slashes=False` is a **security** setting here, not a style choice.
# Starlette's slash redirect builds an *absolute* URL from `scope["scheme"]`, and behind our
# proxy chain that scheme is always `http`: the frontend nginx overwrites `X-Forwarded-Proto`
# with its own (plaintext) `$scheme`, and uvicorn runs without `--proxy-headers` anyway. So
# once TLS terminates at the front proxy (ADR-0016), `POST https://host/v1/auth/login/`
# answers `307 Location: http://host/v1/auth/login` — and 307 preserves method and body, so
# the password goes out in the clear once before the proxy redirects it back to HTTPS. The
# request succeeds, so nothing shows on screen (issue #129).
# Turning the redirect off is safe: no route and no contract path ends in a slash, and the
# router's own 404 already carries the contract error shape (see the handler below).
app = FastAPI(title="adgen-backend", lifespan=lifespan, redirect_slashes=False)

# The contract's error shape is {code, message}; FastAPI's default is {"detail": ...}.
# ⚠️ Register on *Starlette's* HTTPException, not FastAPI's. FastAPI's is a subclass, and
# the 404 for an unmatched route is raised by Starlette's router as the base class — so
# registering the subclass leaves exactly the most common error escaping the contract.
app.add_exception_handler(StarletteHTTPException, api_error_handler)

# ⚠️ The handler above does not cover request validation — FastAPI raises
# `RequestValidationError`, which is not an `HTTPException`. Leaving it out sent the API's
# **most common** error out in FastAPI's own `{"detail": [...]}` shape, with no `code` for a
# client to branch on (2026-08-14 실측).
app.add_exception_handler(RequestValidationError, validation_error_handler)

# ⚠️ And the last resort. `INTERNAL` is in the contract's `ErrorCode`, so a client is told it
# may receive one — but an unhandled exception left as Starlette's plain-text
# `Internal Server Error`, with no JSON at all. The `else` branch in `api_error_handler` was
# written for this and could never run, because that handler is only registered for
# `StarletteHTTPException`.
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(sessions.router)
app.include_router(jobs.router)

# ⚠️ Every router above is behind `current_user`. The template's `/v1/ask` used to sit here
# unauthenticated as a documented exemption; it was deleted once the frontend moved to the
# ad path (API_계약.md 7절). **Do not reintroduce an unauthenticated /v1 route** — the
# contract protects every /v1 path except /health and /v1/auth/* (API_계약.md 6절), and the
# exemption existed only because /v1/ask was not a contract path.

# ⚠️ **And this is not a /v1 path, which is the whole reason it may be unauthenticated.**
# The art-style examples are our own product assets rather than anyone's data, and the
# contract's `ArtStyle.exampleImageUrl` is a bare string with no shape of its own — so the
# serving route was ours to pick (PR #194, 05). `StaticFiles` runs no route dependency, so
# there is no way to put this behind `current_user` short of making it a route, and that
# would be a contract path (갈래 B, 계약 변경 필요).
app.mount(
    "/static/art-styles",
    # ⚠️ `check_dir=False` 입니다. 디렉토리가 없어도 기동해야 합니다 - 파일은 공유
    #    드라이브에서 받아 사람이 볼륨에 넣으므로(구현_범위 4.3절이 생성 이미지 커밋을
    #    금지합니다) 새 배포에는 없는 것이 정상이고, 그때 이 경로만 404 입니다. 기본값
    #    그대로 두면 그 배포가 통째로 뜨지 않습니다. 경로 자체는 위 클래스가 요청마다
    #    설정에서 다시 읽으므로 여기 값은 쓰이지 않습니다.
    _ArtStyleFiles(directory=None, check_dir=False),
    name="art-styles",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe.

    Does not check the AI engine or any upstream API on purpose: this app must stay up and
    serve the fallback path precisely when its dependencies are down.
    """
    return {"status": "ok"}

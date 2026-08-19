"""Runtime settings.

Values come from the environment (infra/.env, never committed). Defaults are the local
docker-compose topology so a fresh clone runs without configuration — a skeleton that
needs a filled-in .env before it moves is not a walking skeleton.

⚠️ The auth fields below have empty defaults, and that emptiness is *not* a usable value.
A committed default signing key is a published signing key (ADR-0013), and the fixed
accounts only exist in infra/.env anyway (ADR-0008). The check that rejects an empty
secret lives in the auth wiring, not here: this class is also read by /health and /v1/ask,
which must keep working on a fresh clone with no .env at all.
"""

import json
from typing import Annotated, Any

from argon2 import extract_parameters
from argon2.exceptions import InvalidHashError
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from backend_core.models.catalog import ArtStyle

# The cookie name is contract surface (openapi.yaml securitySchemes), not an operator
# knob: renaming it silently logs every client out. Kept as a constant so it cannot drift
# per-environment. The *lifetime* is configurable — see Settings.session_max_age_s.
SESSION_COOKIE_NAME = "session_token"


class SeedAccount(BaseModel):
    """One pre-made account. Signup is 501, so accounts only ever arrive this way.

    ⚠️ `password_hash` is a hash, never a plaintext password. Nothing in this codebase
    accepts a plaintext password from configuration — that is how they end up in logs and
    in shell history.
    """

    login_id: str = Field(min_length=1, max_length=64)
    password_hash: str = Field(min_length=1)

    @field_validator("password_hash")
    @classmethod
    def _must_be_a_parseable_argon2_hash(cls, value: str) -> str:
        """Reject a hash that docker-compose ate, or that arrived truncated.

        Compose reads `$` inside a .env value as a variable reference, so an un-escaped
        argon2 hash arrives as `=19=65536,t=3,p=4` — still a non-empty string, so nothing
        downstream notices until a login silently fails. infra/README.md documents the `$$`
        escaping; this check is here because a rule people have to remember is not a defence.

        ⚠️ It parses rather than pattern-matches, and that is the point. A prefix check
        passes `$argon2` and `$argon2id$v=19`, which argon2 then rejects at *login* with
        `InvalidHashError` — and that one is a `ValueError`, not an `Argon2Error`, so it
        escapes the handler in `accounts.authenticate` and reaches the client as a 500
        (2026-08-13 실측). Startup is the right place to find a broken configuration value.
        """
        try:
            extract_parameters(value)
        except InvalidHashError as exc:
            raise ValueError(
                "password hash is not a valid argon2 hash. If it came through "
                "docker-compose, `$` must be written as `$$` in infra/.env "
                "(see infra/README.md, 환경변수 값에 `$`가 들어갈 때). "
                "If it looks right but is short, it was probably truncated on the way in."
            ) from exc
        return value


def _json_list(value: Any, variable: str, example: str) -> Any:
    """Read a JSON list out of an environment variable, treating blank as empty.

    ⚠️ This is not a defensive nicety, it is what lets the stack start unconfigured.
    `docker-compose.yml` writes `${ADGEN_ACCOUNTS:-}` and friends, which set the variable to
    an **empty string** rather than leaving it unset — so without this the field default
    never applies: pydantic-settings tries to JSON-decode `""` and the whole app dies at
    startup with `SettingsError`, before any route exists to report it (2026-08-14 실측 —
    CI 의 종단 관통 테스트가 여기서 unhealthy 로 떨어졌습니다).

    An unconfigured stack is a supported state. Nobody can log in and the catalog is empty,
    while `/health` and `/v1/ask` still answer — which is exactly the "빈 스택이어도 충족"
    deployment the 08-14 일정 항목 asks for.

    Genuinely broken JSON still fails, loudly and **with the shape in the message**: whoever
    hits it is looking at a container that will not start, and the value is one long line in
    a file they cannot see the parser's opinion of. "Invalid JSON" alone does not tell them
    what the valid version looks like, which is the only thing they need.
    """
    if not isinstance(value, str):
        return value
    if not value.strip():
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{variable} is not valid JSON. It is a list, e.g. {example}. "
            "Leave it empty to configure none."
        ) from exc


class Settings(BaseSettings):
    """`ADGEN_` prefix keeps our variables distinguishable from everything else on the host."""

    model_config = SettingsConfigDict(env_prefix="ADGEN_", extra="ignore")

    # Service name of the AI engine in docker-compose; localhost when run bare.
    ai_engine_url: str = "http://localhost:8100"

    # A generation call that overruns this has not been "slow", it has missed the request.
    # We cut it and fall back rather than letting the caller wait.
    ai_engine_timeout_s: float = 8.0

    # `brief:fill` is the one seam with a fallback behind it (ADR-0005): past this we stop
    # waiting, proceed on the user's own input and say `degraded`. 15s because the user is
    # sitting in front of the request — a longer wait buys an inferred `category` at the
    # price of the screen looking frozen.
    brief_fill_timeout_s: float = 15.0

    # The contract promises draft generation inside 60s and `GENERATION_TIMEOUT` past it
    # (API_계약.md 2절). There is no fallback here, so this number *is* the promise.
    draft_timeout_s: float = 60.0

    # How long a client waits between job polls, sent as `Retry-After`. 3s is the contract's
    # initial value and it is a setting because the server has to be able to slow clients
    # down when the queue backs up — the load arrives exactly when there is least room.
    job_poll_interval_s: int = 3

    # How long a single render may take. Minutes, not seconds — the waiter is the job worker
    # and no user is holding a connection open (ADR-0015, API_계약.md 2.1절).
    render_timeout_s: float = 300.0

    # How often the worker looks for queued work. Separate from `job_poll_interval_s`, which
    # is what the *client* is told: the client polls over the network, the worker polls a
    # local file. Tying them together would make slowing clients down also slow rendering.
    worker_poll_interval_s: float = 1.0

    # ⚠️ **On by default**, so a deployment cannot forget it — a stack whose worker is off
    # accepts renders and never runs them, and the symptom is a spinner that resolves for
    # nobody. Only the test suite turns it off (tests/conftest.py), because a worker polling
    # underneath a test flips a job's state between the request and the assertion.
    worker_enabled: bool = True

    # ---- uploaded images (ADR-0010, 세션_보관_정책 2절) ----------------------------------

    # Images go to disk and only their paths into the database — the file is far too big to
    # sit in a row, and 24-hour retention means the cleanup batch (08-25) needs to find them
    # by walking a directory rather than by scanning a table.
    # Under the same volume as the database so one mount carries all durable state
    # (ADR-0014); a second location would be a second thing to back up and forget.
    image_dir: str = "./data/images"

    # ---- retention (세션_보관_정책 2절) --------------------------------------------------

    # ⚠️ These are the periods from the policy table, as settings because the policy says so
    # ("기간 값과 배치 주기는 설정값입니다"). Shortening one shortens how long a user has to
    # come back for their work; lengthening one means holding personal data longer than the
    # document promises. Neither is a tuning knob - change the document first.

    # 업로드 제품 사진. **From upload, not from render.** A session that never reaches
    # finalize would otherwise keep its photo for ever, and the policy rejects that outright.
    retention_photo_h: float = 24.0

    # 브리프와 시안(텍스트), and the session row that carries them.
    retention_session_d: float = 7.0

    # 결과 이미지. ⚠️ This one is also written onto `JobResult.expiresAt` and **sent to the
    # client**, so it is a promise, not just a period. The batch honours the promise over the
    # session period (`retention.sweep`), which means a rendered session lives until
    # `render time + this` -- shortening `retention_session_d` alone has no effect on it.
    retention_result_d: float = 7.0

    # ⚠️ The period is also **how late a deletion can be**. Nothing expires on the dot: a
    # photo passes its 24 hours and then waits for the next pass. With a daily sweep the
    # real retention was up to 48 hours -- twice what 세션_보관_정책 2절's table promises
    # (PR #132 리뷰, 신호정). An hour keeps the gap under 25 hours, and a pass is a scan of
    # a few dozen rows, so the cost is nothing next to holding personal data twice as long.
    # A period rather than a wall-clock time because the process restarts on every deploy and
    # a clock-based schedule would either fire twice or not at all on those days.
    sweep_interval_s: float = 3600.0

    # ⚠️ **On by default**, for the same reason the worker is: a deployment that forgets it
    # keeps personal data past its period, and nothing on screen says so. The test suite
    # turns it off so a sweep does not delete a fixture out from under an assertion.
    sweep_enabled: bool = True

    # ---- catalog -----------------------------------------------------------------------

    # ⚠️ Empty by default, and that is the honest value: **the art-style candidates are not
    # decided** (미결정_대장 A절 3번, 차단). The contract says as much — "이 경로의 응답
    # 모양은 확정이고, 그 안에 실릴 값이 아직 없습니다."
    #
    # A list here rather than a constant in the source so the decision can land as data
    # without a code change, and so nothing in this repo ever looks like the decision was
    # made. JSON, same shape as `ArtStyle`.
    art_styles: Annotated[list[ArtStyle], NoDecode] = Field(default_factory=list)

    @field_validator("art_styles", mode="before")
    @classmethod
    def _parse_art_styles(cls, value: Any) -> Any:
        """Same empty-string handling as `accounts` — see `_json_list` for why."""
        return _json_list(
            value,
            "ADGEN_ART_STYLES",
            '[{"artStyleId": "...", "name": "...", "exampleImageUrl": "..."}]',
        )

    # ---- storage (ADR-0010) ------------------------------------------------------------

    # One SQLite file holds accounts, sessions, briefs, drafts and jobs. Configurable
    # because a constant here splits local development from the VM deployment, where the
    # file has to live on a mounted path to survive `docker compose up` (ADR-0010).
    # `.sqlite` rather than `.sqlite3` so the repo's existing ignore rule covers it:
    # this file holds uploaded-photo paths and briefs, and the repo is public.
    db_path: str = "./data/adgen.sqlite"

    # ---- auth (ADR-0008, ADR-0013) -----------------------------------------------------

    # Signs the session token. No default: see the module docstring.
    session_secret: str = ""

    # 24h, no refresh (세션_보관_정책.md 1.4절). Configurable because the number is a
    # guess about the theft window, and a guess in code needs a deploy to revise.
    session_max_age_s: int = 86400

    # JSON list, e.g. [{"login_id": "...", "password_hash": "$argon2id$..."}].
    # snake_case, not the contract's camelCase: this is operator configuration, not wire
    # format. Nothing here is ever serialised to a client.
    # Two accounts are the minimum that can prove INV-9 — with one, "someone else's
    # session" does not exist and the 404 path is never taken (ADR-0008). Not enforced
    # here: individual devs may seed extra accounts locally (구현_범위.md 1절).
    #
    # `NoDecode` takes the JSON parsing away from pydantic-settings so the validator below
    # can see the raw string — see it for why an empty one has to survive.
    accounts: Annotated[list[SeedAccount], NoDecode] = Field(default_factory=list)

    @field_validator("accounts", mode="before")
    @classmethod
    def _parse_accounts(cls, value: Any) -> Any:
        return _json_list(
            value,
            "ADGEN_ACCOUNTS",
            '[{"login_id": "...", "password_hash": "$argon2id$..."}]',
        )


def get_settings() -> Settings:
    """Read settings. Callers cache — see api.deps, which holds the single instance."""
    return Settings()

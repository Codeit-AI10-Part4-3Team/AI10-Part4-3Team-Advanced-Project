#!/usr/bin/env python3
"""실패 모드 4종을 **도는 스택**에 대고 잽니다 (05, e2e/README.md "아직 자동화하지 않은 것").

단위 시험은 이 분기들을 이미 덮고 있습니다 (`apps/backend/tests/backend_core/test_render.py`
등). 이 스크립트가 답하는 것은 다른 질문입니다 - **컨테이너가 실제로 죽거나 멎었을 때 같은
일이 나는가.** 목이 아니라 진짜 스택이라, 배선이 바뀌면 여기서 걸립니다.

    python3 scripts/check_failure_modes.py --dry-run     # 무엇을 할지만 찍습니다
    python3 scripts/check_failure_modes.py
    python3 scripts/check_failure_modes.py --out ~/failure-modes.md   # 진행 기록용 기록

⚠️ **e2e 하네스가 아니라 별도 스크립트인 이유가 있습니다.** `e2e/README.md` 가 "열화 경로
자동화는 하네스가 docker 를 직접 다루게 되므로 그 결합을 감수할지가 먼저 정해져야 합니다" 를
적어 두었고, 그것은 아직 정해지지 않았습니다. 여기서 docker 를 다루면 그 결정을 열지 않고,
`종단 관통 테스트` 잡에도 영향이 없습니다. **정해지면 이 파일을 e2e 로 옮기는 것이 맞습니다.**

⚠️ **시연 중에는 돌리지 마세요.** 도는 동안 시안 생성이 실제로 실패하고, B 검사는 60초 가까이
멎어 있습니다. 공유 VM 이면 먼저 알리세요.

## stop 과 pause 를 가르는 이유

`backend_core/ai_client.py` 가 `httpx.TimeoutException` 을 `GenerationTimeoutError` 로,
나머지 `HTTPError` 를 `AiEngineUnavailableError` 로 나누고, 라우트와 렌더 워커가 **둘을 다른
응답으로 매핑**합니다 (504 / 503, 잡 error.code 도 갈립니다). 컨테이너를 `stop` 하면 커널이
연결을 거부해 앞쪽만 지나고, **뒤쪽은 한 줄도 안 지나갑니다.**

`pause` 는 cgroup freezer 로 프로세스만 얼립니다. 리스닝 소켓은 커널에 남아 연결은 되는데
응답이 오지 않으므로, 그것이 타임아웃 갈래를 태우는 무해한 방법입니다.

**네 기대값은 2026-08-28 에 로컬에서 실측했습니다.** A 는 `201 brief_filling degraded`,
B 는 `504 GENERATION_TIMEOUT` 이 60.2초에 오고 세션이 `brief_ready` 로 돌아왔으며(ADR-0012),
C 는 `200 failed UPSTREAM_UNAVAILABLE`, D 는 `done` + `image/webp` 였습니다.

⚠️ **다만 B 는 `docker pause` 가 아니라 블랙홀 소켓으로 쟀습니다** - 연결은 받고 응답하지 않는
포트를 8100 에 세웠습니다. **재는 조건(소켓은 살아 있고 응답이 없음)은 같지만, `docker pause`
가 정말 그 조건을 만드는지는 이 스크립트를 처음 돌릴 때 확인됩니다.** B 가 504 가 아니라 503
으로 나오면 그 전제가 틀린 것이며, **그 사실 자체가 보고할 값입니다.** 기대값을 고치기 전에
왜 그런지부터 보세요.

## 예외는 `brief:fill` 하나입니다

그 이음매만 타임아웃과 다운을 안 가릅니다 - `ai_client.py` 가 "호출자의 답이 어느 쪽이든
같아서" 라고 명시합니다 (ADR-0005 의 열화가 유일하게 허용된 자리). 그래서 A 는 `stop` 으로
충분합니다.

## 결과 처리

이 스크립트는 CI 가 돌리지 않습니다. 출력은 사람이 `docs/역할_일정/05-백엔드_인프라.md` 진행
기록에 붙이며, 2026-08-19 열화 실측과 같은 형식입니다 - **언제 무엇을 확인했는가**의 증빙입니다.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from email.message import Message as EmailMessage
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "infra" / "docker-compose.yml"
ENV_FILE = ROOT / "infra" / ".env"

# 이 스크립트가 만지는 서비스는 하나뿐입니다. 상수로 둔 것은 인자로 받지 않기 위해서입니다 -
# 잘못 넘긴 이름 하나가 backend 나 caddy 를 멈추면 증상이 이 스크립트의 실패로 보이지 않습니다.
SERVICE = "ai-engine"

# 허용 동사. **`down` 과 `rm` 은 여기 없고, 넣지 마세요** - `adgen-state` 볼륨에 계정과 세션이
# 들어 있고 되돌릴 방법은 백업뿐입니다 (AGENTS.md, infra/README.md).
VERBS = ("stop", "start", "pause", "unpause", "up", "ps", "exec")

# B 검사가 기다리는 상한. 서버측 `draft_timeout_s` 기본값이 60초이므로 그보다 넉넉해야
# **클라이언트가 먼저 포기해 무엇을 쟀는지 알 수 없게 되는 일**을 막습니다.
HTTP_TIMEOUT_S = 180

# 잡 폴링 상한. 스텁 렌더는 초 단위이고 실패는 더 빠릅니다. e2e 의 240초보다 짧게 둔 것은
# 이 스크립트가 실물 모드를 기본으로 거부하기 때문입니다.
JOB_DEADLINE_S = 120

# healthy 를 기다리는 상한. `infra/docker-compose.yml` 의 ai-engine healthcheck 에서 옵니다 -
# `interval` 10초 x (`retries` 5 + 1). **도커가 컨테이너를 unhealthy 로 확정하는 창과 같고,**
# 그 안에 healthy 가 안 되면 기다림이 모자란 것이 아니라 정말 고장입니다. 실측 회복은 9초
# (probe 한 번, 2026-08-28) - 상한이 여섯 배 넉넉한 것은 부하가 걸린 VM 을 위해서입니다.
HEALTH_DEADLINE_S = 60

# `api/routes/auth.py` 의 `SESSION_COOKIE_NAME` 과 같은 값입니다.
SESSION_COOKIE = "session_token"

BASE_URL_ENV = "E2E_BASE_URL"
LOGIN_ID_ENV = "E2E_LOGIN_ID"
PASSWORD_ENV = "E2E_PASSWORD"  # noqa: S105 - 환경변수 이름이지 값이 아닙니다


# ── 출력 ────────────────────────────────────────────────────────────────────────


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def warn(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr, flush=True)


def mask(url: str) -> str:
    """공개 호스트를 가립니다.

    ⚠️ 배포의 `ADGEN_PUBLIC_HOST` 는 `<외부 IP>.sslip.io` 형태라 **그 문자열 자체가 외부
    IP** 입니다. 저장소가 public 이고 이 출력은 진행 기록에 붙습니다
    (GCP_VM_사용_가이드.md 2-b절). 로컬 주소는 가릴 것이 없으므로 그대로 둡니다.
    """
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return url
    return "<공개호스트>"


# ── docker compose ──────────────────────────────────────────────────────────────


class Compose:
    """`docker compose` 호출. 동사와 대상을 좁혀 둡니다."""

    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run

    def _run(self, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
        if args[0] not in VERBS:
            raise ValueError(f"허용되지 않은 동사입니다: {args[0]} (허용: {', '.join(VERBS)})")
        command = [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "--env-file",
            str(ENV_FILE),
            *args,
        ]
        if self.dry_run:
            print(f"    [dry-run] {' '.join(command)}")
            return subprocess.CompletedProcess(command, 0, "", "")
        # 인자는 위 VERBS 로 좁힌 상수와 서비스 이름 하나뿐이고, 셸을 거치지 않습니다.
        return subprocess.run(command, capture_output=capture, text=True, check=False)

    def stop(self) -> None:
        log(f"{SERVICE} 정지")
        self._run("stop", SERVICE)

    def pause(self) -> None:
        log(f"{SERVICE} 일시 정지 (freezer)")
        self._run("pause", SERVICE)

    def unpause(self) -> None:
        self._run("unpause", SERVICE)

    def up(self) -> bool:
        """다시 띄우고 healthy 까지 기다립니다.

        ⚠️ **`unpause` 를 먼저 부릅니다.** 이미 돌고 있으면 그 `unpause` 는 실패하고 그 실패는
        무해합니다.

        ⚠️ **`--wait` 를 쓰지 않고 직접 폴링합니다.** `unpause` 직후 컨테이너는 `running` 인데
        **`unhealthy` 이고, 다음 probe 가 성공할 때까지 그대로 남습니다.** `up --wait` 는 그
        상태를 기다리지 않고 `container is unhealthy` 로 **1초 만에 종료 코드 1** 을 냅니다 -
        그러면 B 다음의 C, D, 복구 판정이 **엔진이 멀쩡한데도** 전부 거짓 실패로 찍힙니다
        (PR #304 리뷰가 잡았습니다).

        `로컬에서 확인함` (2026-08-28, 같은 healthcheck 값으로 격리 프로젝트를 세워 실측):

            pause 직후            paused  (health 는 빈 문자열)
            unpause 직후          running unhealthy
            up -d --wait          "is unhealthy", 1초, rc=1
            healthy 로 회복        9초
            이 함수의 폴링          11.1초 만에 True

        회복이 `interval`(10초) 언저리인 것은 probe 한 번을 기다리기 때문입니다.
        """
        self._run("unpause", SERVICE)
        self._run("up", "-d", "--no-deps", SERVICE)
        return self.wait_healthy()

    def wait_healthy(self) -> bool:
        """`running` + `healthy` 가 될 때까지 기다립니다."""
        if self.dry_run:
            return True
        deadline = time.monotonic() + HEALTH_DEADLINE_S
        while True:
            state, health = self.status()
            # healthcheck 가 없는 서비스는 `Health` 가 빈 문자열입니다. 그때는 `running` 이
            # 우리가 알 수 있는 전부입니다.
            if state == "running" and health in {"healthy", ""}:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(2)

    def ready(self) -> bool:
        """검사가 자기 전제를 스스로 세웁니다.

        ⚠️ **각 검사는 앞 검사가 무엇을 해 놓았는지 가정하지 않습니다.** 가정했더니 A 가
        엔진을 정지한 채 끝나고 B 와 C 가 준비 단계에서만 실패했습니다 - `pause` 는 한 번도
        불리지 않았고, **이 스크립트가 존재하는 이유인 타임아웃 갈래를 한 줄도 지나지
        않았습니다** (2026-08-28 실측). 검사 순서를 바꾸거나 하나만 골라 돌려도 서게 하려면
        전제를 여기서 세워야 합니다.
        """
        log(f"{SERVICE} 기동 확인")
        return self.up()

    def generation_mode(self) -> str | None:
        """`None` 은 **읽지 못했다**는 뜻이고 "미설정" 과 다릅니다.

        ⚠️ 둘을 같은 값으로 접었더니 앞선 회차가 엔진을 정지한 채 끝난 상태에서 "생성 모드가
        `미설정` 입니다. 정말 돌리려면 --allow-model 을 붙이세요" 가 나왔습니다. **그 말을
        따르면 모드를 모르는 채로 전 구간을 돌게 되고, 배포가 실물이었다면 요금이 나갑니다** -
        이 가드가 막으려던 바로 그것입니다 (2026-08-28 자체 리뷰에서 재현).
        """
        done = self._run("exec", "-T", SERVICE, "printenv", "ADGEN_GENERATION_MODE", capture=True)
        if done.returncode != 0:
            return None
        return (done.stdout or "").strip() or "미설정"

    def status(self) -> tuple[str, str]:
        """`(state, health)`. 컨테이너가 없으면 `("없음", "")`.

        ⚠️ **둘을 갈라 받는 것이 요점입니다.** `running` 인데 아직 `unhealthy` 인 것과 정말
        못 살린 것은 사람이 할 일이 다릅니다 - 앞은 기다리면 되고 뒤는 손으로 봐야 합니다.
        """
        done = self._run("ps", "--format", "{{.Service}} {{.State}} {{.Health}}", capture=True)
        for line in (done.stdout or "").splitlines():
            if line.startswith(f"{SERVICE} "):
                parts = line.split()
                return parts[1], parts[2] if len(parts) > 2 else ""
        return "없음", ""


# ── HTTP ────────────────────────────────────────────────────────────────────────


class Response:
    def __init__(self, status: int, headers: EmailMessage, body: bytes) -> None:
        self.status = status
        self.body = body
        # ⚠️ `Set-Cookie` 는 여러 줄로 올 수 있어 dict 로 접으면 하나만 남습니다. 그래서
        #    조회용 dict 와 별도로 원본 목록을 들고 있습니다.
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.set_cookies: list[str] = headers.get_all("Set-Cookie", [])

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            return {}

    def code(self) -> str:
        """계약 오류 본문의 `code`. 없으면 빈 문자열."""
        body = self.json()
        return body.get("code", "") if isinstance(body, dict) else ""


class Http:
    """세션을 들고 다니는 최소 클라이언트.

    표준 라이브러리만 씁니다 - `scripts/observe.py` 와 같은 방침입니다. VM 에 새 의존을 만들지
    않으려는 것이고, e2e venv(httpx, Pillow)가 없어도 이 스크립트가 돕니다.

    ⚠️ **쿠키 병을 쓰지 않고 `Cookie` 헤더를 직접 답니다.** 세션 쿠키에는 `Secure` 가 붙어
    있는데(ADR-0013), `http.cookiejar` 는 그런 쿠키를 평문 HTTP 로 **보내지 않습니다** -
    브라우저와 달리 `localhost` 예외가 없습니다. 그대로 두면 로그인은 200 인데 다음 요청이
    401 이고, **증상이 인증 결함처럼 보입니다.** `e2e/conftest.py` 의 `_sign_in` 이 같은
    이유로 같은 우회를 씁니다 (2026-08-19 실측, 이 스크립트에서도 재현했습니다).
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> Response:
        request = urllib.request.Request(  # noqa: S310 - 스킴은 아래에서 확인합니다
            f"{self.base_url}{path}", data=body, method=method
        )
        if request.type not in {"http", "https"}:
            raise ValueError(f"http/https 만 지원합니다: {request.type}")
        if content_type:
            request.add_header("Content-Type", content_type)
        if self.cookie:
            request.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as answer:  # noqa: S310
                return Response(answer.status, answer.headers, answer.read())
        except urllib.error.HTTPError as error:
            # ⚠️ 4xx 와 5xx 도 **응답이지 예외가 아닙니다.** 이 스크립트가 재려는 것의 절반이
            #    503, 504 라 여기서 던지면 잴 것이 사라집니다.
            return Response(error.code, error.headers, error.read())
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            # ⚠️ 응답이 아예 오지 않은 경우입니다 - backend 자체가 안 떴거나, 서버측 상한이
            #    `HTTP_TIMEOUT_S` 보다 커서 우리가 먼저 포기했거나. 트레이스백으로 죽으면
            #    `finally` 의 복구는 돌지만 **무엇을 재다 죽었는지가 판정 표에 안 남습니다.**
            #    `000` 은 curl 이 같은 상황에 쓰는 값이고 `deploy-vm.sh` 도 그렇게 씁니다.
            warn(f"{method} {path}: 응답 없음 ({error})")
            return Response(0, EmailMessage(), b"")

    def hold_session(self, answer: Response) -> bool:
        """로그인 응답의 `session_token` 을 뽑아 이후 요청에 답니다."""
        for raw in answer.set_cookies:
            name, _, rest = raw.partition("=")
            if name.strip() == SESSION_COOKIE:
                self.cookie = f"{SESSION_COOKIE}={rest.split(';', 1)[0]}"
                return True
        return False

    def get(self, path: str) -> Response:
        return self.request("GET", path)

    def post_json(self, path: str, payload: dict[str, Any]) -> Response:
        return self.request(
            "POST", path, body=json.dumps(payload).encode(), content_type="application/json"
        )

    def post(self, path: str) -> Response:
        return self.request("POST", path)

    def post_form(self, path: str, fields: dict[str, str], image: bytes) -> Response:
        body, content_type = _multipart(fields, image)
        return self.request("POST", path, body=body, content_type=content_type)


def _multipart(fields: dict[str, str], image: bytes) -> tuple[bytes, str]:
    """계약 8.1절의 단일 multipart 요청을 손으로 만듭니다."""
    boundary = f"----adgen{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="productImage"; filename="product.png"\r\n'
        "Content-Type: image/png\r\n\r\n".encode()
    )
    parts.append(image)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def product_image(size: int = 768) -> bytes:
    """계약을 통과하는 제품 사진을 만듭니다 (PNG, 짧은 변 512px 이상).

    Pillow 를 쓰지 않는 이유는 `scripts/` 에 새 의존을 들이지 않기 위해서입니다. e2e 의 같은
    픽스처는 Pillow 를 쓰고, 그쪽은 이미 그 의존을 갖고 있습니다.

    파일로 커밋하지 않는 이유는 e2e 와 같습니다 - 루트 `.gitignore` 가 화이트리스트 방식이라
    새 바이너리가 조용히 빠집니다 (AGENTS.md).
    """
    row = b"\x00" + bytes((208, 190, 160)) * size
    raw = row * size

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# ── 광고 경로 ───────────────────────────────────────────────────────────────────


def create_session(http_client: Http, image: bytes, name: str) -> Response:
    return http_client.post_form(
        "/v1/sessions",
        {
            "outputType": "single_ad",
            "productName": name,
            "sellingPoint": "원두를 주문 후에 갈아 내려 산미가 살아 있습니다. 500g 한 봉지입니다.",
            "note": "따뜻한 일상 분위기로 부탁합니다.",
        },
        image,
    )


def poll_job(http_client: Http, job_id: str) -> tuple[Response, dict[str, Any]]:
    """잡이 끝날 때까지 봅니다.

    ⚠️ **렌더가 실패해도 조회는 200 입니다.** 그것이 계약이며, 여기서 4xx/5xx 를 섞으면
    "서버에 못 닿았다" 와 "그림을 못 만들었다" 가 구별되지 않습니다.
    """
    deadline = time.monotonic() + JOB_DEADLINE_S
    while True:
        answer = http_client.get(f"/v1/jobs/{job_id}")
        job = answer.json()
        if answer.status != 200 or job.get("status") in {"done", "failed"}:
            return answer, job
        if time.monotonic() >= deadline:
            return answer, job
        retry_after = answer.headers.get("retry-after", "")
        time.sleep(max(int(retry_after), 1) if retry_after.isdigit() else 3)


# ── 검사 ────────────────────────────────────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, bool]] = []
        self.sessions: list[str] = []

    def check(self, label: str, expected: str, actual: str) -> bool:
        ok = expected == actual
        self.rows.append((label, expected, actual, ok))
        mark = "OK" if ok else "실패"
        print(f"  {label:<34} {actual:<38} {mark}", flush=True)
        if not ok:
            print(f"  {'':<34} 기대: {expected}", flush=True)
        return ok

    @property
    def failures(self) -> int:
        return sum(1 for *_, ok in self.rows if not ok)

    def as_markdown(self, *, host: str, mode: str, restored: bool) -> str:
        """진행 기록에 그대로 붙일 수 있는 형태로 씁니다.

        목적지가 `docs/역할_일정/05-백엔드_인프라.md` 진행 기록이라 JSON 이 아니라 마크다운
        입니다. 그 기록이 답하는 질문은 "언제 무엇을 확인했는가" 이고, 사람이 읽습니다.

        ⚠️ **재지 않은 것을 함께 적습니다.** 결과만 적힌 기록은 다음 사람에게 실제보다 넓게
        읽히고, 이 저장소가 반복해서 당한 실패가 정확히 그것입니다 (스텁 숫자를 지표로 읽는
        것, skip 을 통과로 읽는 것). 아래 "이 회차가 답하지 않는 것" 은 지우지 마세요.
        """
        stamp = time.strftime("%Y-%m-%d %H:%M:%S%z")
        lines = [
            f"#### 실패 모드 4종 확인 ({stamp})",
            "",
            f"`scripts/check_failure_modes.py`. 대상 {host}, 생성 모드 `{mode}`.",
            "",
            "| 검사 | 기대 | 실제 | 판정 |",
            "|---|---|---|---|",
        ]
        for label, expected, actual, ok in self.rows:
            lines.append(
                f"| {label.strip()} | `{expected}` | `{actual}` | {'OK' if ok else '실패'} |"
            )
        lines += [
            "",
            f"복구: {'확인함' if restored else '**실패 - 손으로 확인하세요**'}."
            f" 남긴 세션 {len(self.sessions)}건 (보존 정리 배치가 치웁니다).",
            "",
            "**이 회차가 답하지 않는 것**",
            "",
            "- 가드레일 거절(`CONTENT_POLICY_REJECTED`)은 스텁이 거절하지 않아 재현 조건이"
            " 없습니다 (e2e/README.md).",
            "- 만화형은 관통 대상이 아닙니다 (구현_범위 1절). 여기서 지나간 것은 단일 광고형"
            " 하나입니다.",
            "- 지연 값은 지표가 아닙니다. 스텁 구간의 숫자는 자기 자신과의 일치율입니다"
            " (AGENTS.md 현재 상태).",
        ]
        return "\n".join(lines) + "\n"


def check_a_degraded(http_client: Http, compose: Compose, report: Report, image: bytes) -> None:
    """엔진이 죽어도 세션 생성은 지나갑니다 (ADR-0005).

    이 프로젝트에 남은 열화는 이것 하나뿐이고, 나머지 이음매는 명시적으로 실패합니다.
    """
    log("A. 열화 - ai-engine 을 정지한 채 세션 생성")
    compose.stop()
    answer = create_session(http_client, image, "열화 확인 커피")
    session = answer.json()
    if session.get("sessionId"):
        report.sessions.append(session["sessionId"])
    report.check(
        "A  열화 (stop)",
        "201 brief_filling degraded",
        f"{answer.status} {session.get('state', '?')} {session.get('messageMode', '?')}",
    )


def check_b_draft_timeout(
    http_client: Http, compose: Compose, report: Report, image: bytes
) -> None:
    """멎은 엔진은 다운과 다른 갈래를 태웁니다 - 504 이고, 브리프 잠금이 풀립니다.

    두 번째 확인이 본체입니다. ADR-0012 는 시안 생성이 실패하면 세션을 `brief_ready` 로
    되돌리라고 정하는데, 그러지 않으면 사용자가 **브리프는 잠겼고 보여 줄 시안은 없는** 세션에
    갇힙니다. 상태 코드만 보면 그 일이 안 났는지 알 수 없습니다.
    """
    log("B. 시안 타임아웃 - 엔진을 얼린 채 시안 생성 (서버측 상한만큼 걸립니다)")
    if not compose.ready():
        report.check("B  준비 (엔진 기동)", "healthy", "기동 실패")
        return
    answer = create_session(http_client, image, "타임아웃 확인 커피")
    session = answer.json()
    session_id = session.get("sessionId", "")
    if session_id:
        report.sessions.append(session_id)
    if answer.status != 201 or session.get("state") != "brief_ready":
        report.check(
            "B  준비 (세션이 brief_ready)",
            "201 brief_ready",
            f"{answer.status} {session.get('state', '?')}",
        )
        return

    compose.pause()
    try:
        drafted = http_client.post(f"/v1/sessions/{session_id}/draft")
    finally:
        compose.unpause()

    report.check(
        "B  시안 타임아웃 (pause)",
        "504 GENERATION_TIMEOUT",
        f"{drafted.status} {drafted.code() or '?'}",
    )
    after = http_client.get(f"/v1/sessions/{session_id}").json()
    report.check("B  브리프 잠금 해제 (ADR-0012)", "brief_ready", str(after.get("state", "?")))


def check_c_render_fails(http_client: Http, compose: Compose, report: Report, image: bytes) -> None:
    """렌더에는 폴백이 없습니다. 잡이 명시적으로 실패해야 합니다 (ADR-0005).

    ⚠️ 조회는 200 이고 잡이 `failed` 입니다. 그 둘이 같은 층이 아니라는 것이 계약입니다.
    """
    log("C. 렌더 실패 - 시안까지 간 뒤 엔진을 정지하고 확정")
    if not compose.ready():
        report.check("C  준비 (엔진 기동)", "healthy", "기동 실패")
        return
    answer = create_session(http_client, image, "렌더 실패 확인 커피")
    session = answer.json()
    session_id = session.get("sessionId", "")
    if session_id:
        report.sessions.append(session_id)
    drafted = http_client.post(f"/v1/sessions/{session_id}/draft") if session_id else answer
    if drafted.status != 200:
        report.check("C  준비 (시안 생성)", "200 draft_ready", f"{drafted.status} ?")
        return

    compose.stop()
    accepted = http_client.post(f"/v1/sessions/{session_id}/finalize")
    if accepted.status != 202:
        report.check("C  준비 (확정 접수)", "202", str(accepted.status))
        return
    polled, job = poll_job(http_client, accepted.json()["jobId"])
    error_code = (job.get("error") or {}).get("code", "?")
    report.check(
        "C  렌더 실패 (stop)",
        "200 failed UPSTREAM_UNAVAILABLE",
        f"{polled.status} {job.get('status', '?')} {error_code}",
    )


def check_d_recovers(http_client: Http, compose: Compose, report: Report, image: bytes) -> None:
    """대조군. 앞 셋이 스택을 망가뜨린 채 끝나지 않았다는 증명입니다.

    이것이 없으면 A ~ C 가 전부 OK 인데 서비스는 죽어 있는 상태를 초록으로 보고할 수 있습니다.
    """
    log("D. 복구 - 엔진을 되살리고 전 구간")
    if not compose.ready():
        report.check("D  복구 (엔진 기동)", "healthy", "기동 실패")
        return

    answer = create_session(http_client, image, "복구 확인 커피")
    session = answer.json()
    session_id = session.get("sessionId", "")
    if session_id:
        report.sessions.append(session_id)
    if answer.status != 201 or session.get("state") != "brief_ready":
        report.check(
            "D  복구 (세션 생성)",
            "201 brief_ready",
            f"{answer.status} {session.get('state', '?')}",
        )
        return

    drafted = http_client.post(f"/v1/sessions/{session_id}/draft")
    accepted = http_client.post(f"/v1/sessions/{session_id}/finalize")
    if drafted.status != 200 or accepted.status != 202:
        report.check("D  복구 (시안과 확정)", "200 / 202", f"{drafted.status} / {accepted.status}")
        return

    _, job = poll_job(http_client, accepted.json()["jobId"])
    image_type = "?"
    if job.get("status") == "done":
        image_type = http_client.get(job["result"]["imageUrl"]).headers.get("content-type", "?")
    report.check("D  복구 (전 구간)", "done image/webp", f"{job.get('status', '?')} {image_type}")


# ── main ────────────────────────────────────────────────────────────────────────


def sign_in(http_client: Http, login_id: str, password: str) -> bool:
    answer = http_client.post_json("/v1/auth/login", {"loginId": login_id, "password": password})
    if answer.status != 200:
        warn(f"로그인 실패: {answer.status} {answer.code()}")
        return False
    if not http_client.hold_session(answer):
        warn(f"로그인 응답에 `{SESSION_COOKIE}` 쿠키가 없습니다.")
        return False
    return True


def restore(compose: Compose) -> bool:
    """무슨 일이 있어도 엔진을 되살리고 **확인까지** 합니다.

    ⚠️ 이 스크립트에서 제일 위험한 자리입니다. 중간에 죽으면 배포된 서비스가 시안 생성 없이
    남고, 증상이 이 스크립트와 무관해 보입니다. `unpause` 를 먼저 부르는 것은 얼어 있는
    컨테이너에는 `up -d` 가 닿지 않기 때문입니다.
    """
    log("복구")
    ok = compose.up()
    state, health = compose.status()
    if ok:
        print(f"  복구 확인: {SERVICE} {state} {health or '(healthcheck 없음)'}")
        return True

    # ⚠️ **두 경우를 가릅니다.** 앞은 기다리면 풀리고 뒤는 사람이 봐야 합니다. 하나로 접어
    #    두면 멀쩡한 스택을 두고 없는 장애를 찾으러 들어갑니다 (PR #304 리뷰).
    if state == "running":
        warn(
            f"{SERVICE} 는 running 인데 {HEALTH_DEADLINE_S}초 안에 healthy 가 되지 않았습니다"
            f" (health={health or '없음'})."
        )
        warn("컨테이너는 살아 있습니다. 잠시 뒤 다시 보세요:")
    else:
        warn(f"{SERVICE} 를 되살리지 못했습니다 (상태: {state}).")
        warn("손으로 확인하세요:")
    warn(f"  docker compose -f {COMPOSE_FILE} --env-file {ENV_FILE} ps")
    return False


def print_plan() -> None:
    """`--dry-run` 이 찍는 것.

    ⚠️ **여기서 "통과" 를 찍지 않습니다.** dry-run 은 아무것도 재지 않았고, 재지 않은 것을
    초록으로 보고하는 것이 이 저장소가 반복해서 당한 실패 모양입니다 (e2e 가 URL 없이 전부
    skip 하고도 종료 코드 0 이던 건 - e2e/README.md).
    """
    print("  아무것도 만지지 않습니다. 실제 실행은 아래 순서로 돕니다.\n")
    up = f"unpause + up -d {SERVICE} + health 폴링"
    # ⚠️ **검사마다 앞에 기동 확인이 붙습니다.** 앞 검사가 남긴 상태를 가정하지 않기 때문이고,
    #    가정했더니 A 가 엔진을 정지한 채 끝나 B 와 C 가 준비 단계에서만 실패했습니다.
    steps = (
        ("A  열화", f"compose stop {SERVICE}", "POST /v1/sessions -> 201 brief_filling degraded"),
        ("B  기동 확인", up, "앞 검사가 정지시켜 두었습니다"),
        (
            "B  시안 타임아웃",
            f"compose pause {SERVICE}",
            "POST .../draft -> 504 GENERATION_TIMEOUT",
        ),
        ("B  잠금 해제", f"compose unpause {SERVICE}", "GET /v1/sessions/{id} -> brief_ready"),
        ("C  기동 확인", up, "시안까지 가려면 엔진이 있어야 합니다"),
        ("C  렌더 실패", f"compose stop {SERVICE}", "확정 후 폴링 -> failed UPSTREAM_UNAVAILABLE"),
        ("D  복구", up, "전 구간 -> done image/webp"),
        ("복구(finally)", up, "running 과 healthy 를 갈라 확인"),
    )
    for label, verb, expected in steps:
        print(f"  {label:<18} {verb:<44} {expected}")
    print("\n  걸리는 시간: 2 ~ 3분. B 만 서버측 상한(기본 60초)을 실제로 기다립니다.")
    print("  아무것도 재지 않았습니다 - `--dry-run` 을 빼야 판정이 나옵니다.")


def arm_signals() -> None:
    """SIGTERM 과 SIGHUP 을 Ctrl-C 와 같은 경로로 보냅니다.

    ⚠️ **SSH 가 끊기면 셸이 SIGHUP 을 보내고 파이썬은 기본 처분으로 즉시 죽습니다** -
    `finally` 가 돌지 않아 공유 VM 에 ai-engine 이 정지 또는 얼어 있는 채로 남습니다. 증상은
    "시안 생성만 안 됨" 이라 이 스크립트와 무관해 보입니다. B 검사가 60초 넘게 멈춰 있으므로
    그 창이 실제로 넓습니다 (PR #304 리뷰, 신호정. SIGTERM 실측 exit 143, finally 출력 없음).

    ⚠️ 그래도 `tmux` 나 `nohup` 안에서 돌리는 편이 낫습니다. 이 처리는 신호를 받을 수 있을
    때만 돕니다 - `SIGKILL` 과 전원 차단에는 방법이 없습니다.
    """

    def interrupt(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    if hasattr(signal, "SIGHUP"):  # 윈도우에는 없습니다
        signal.signal(signal.SIGHUP, interrupt)


def write_record(
    path: Path,
    report: Report,
    host: str,
    mode: str,
    restored: bool,
    interrupted: bool,
) -> None:
    """판정을 파일로 남깁니다. 실패해도 검사 결과를 잃지 않습니다."""
    text = report.as_markdown(host=host, mode=mode, restored=restored)
    if interrupted:
        text = (
            "> ⚠️ **중단된 회차입니다.** 아래는 멈추기 전까지 잰 것이고, 나머지 검사는\n"
            "> 돌지 않았습니다. 완주한 회차로 읽지 마세요.\n\n"
        ) + text
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        # 파일을 못 써도 판정은 이미 화면에 있습니다. 여기서 죽으면 그것까지 잃습니다.
        warn(f"기록을 쓰지 못했습니다 ({path}): {error}")
        return
    print(f"  기록: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="무엇을 할지만 찍고 만지지 않습니다")
    parser.add_argument(
        "--allow-model",
        action="store_true",
        help="실물 모드에서도 돌립니다. D 검사가 실제 렌더를 사므로 요금이 나갑니다",
    )
    parser.add_argument(
        "--out",
        metavar="경로",
        help="판정을 마크다운으로 남깁니다. 05 진행 기록에 그대로 붙일 수 있는 형태입니다",
    )
    args = parser.parse_args()

    # ⚠️ 배포 체크아웃 안에 쓰면 다음 배포의 사전 점검이 "추적되지 않는 파일" 로 경고합니다
    #    (e2e venv 를 체크아웃 밖에 만드는 것과 같은 이유 - e2e/README.md). 막지는 않습니다,
    #    로컬 클론에서는 정상적인 자리이기 때문입니다.
    out_path = Path(args.out).expanduser() if args.out else None
    if out_path is not None and out_path.resolve().is_relative_to(ROOT):
        warn(f"{out_path} 가 체크아웃 안입니다. 배포 VM 이면 밖에 두세요 (예: ~/failure-modes.md).")

    base_url = os.environ.get(BASE_URL_ENV) or "http://localhost"

    # ⚠️ **`--dry-run` 은 아무 전제도 요구하지 않습니다.** 계정도 `.env` 도 스택도 필요 없습니다 -
    #    하는 일이 계획을 찍는 것뿐이기 때문입니다. 아래 검사들을 먼저 두었더니 새 체크아웃에서
    #    `--dry-run` 이 `.env` 가 없다고 멈췄습니다. "아무것도 만지지 않습니다" 라면서 전제를
    #    요구하면 읽는 사람이 둘 중 무엇을 믿어야 할지 알 수 없습니다.
    if args.dry_run:
        print(f"스택: {mask(base_url)} / 생성 모드 확인 안 함\n")
        print_plan()
        return 0

    login_id = os.environ.get(LOGIN_ID_ENV)
    password = os.environ.get(PASSWORD_ENV)

    # ⚠️ 계정이 없으면 **skip 이 아니라 실패**입니다. 초록인데 아무것도 재지 않은 상태가
    #    e2e/README.md 가 경고하는 실패 모양이고, 이 스크립트는 그것을 만들지 않습니다.
    if not login_id or not password:
        warn(f"{LOGIN_ID_ENV} / {PASSWORD_ENV} 가 필요합니다. 계정이 시드된 스택에서 돌리세요.")
        return 1
    if not COMPOSE_FILE.exists():
        warn(f"{COMPOSE_FILE} 이 없습니다. 레포 루트에서 돌리세요.")
        return 1
    # ⚠️ compose 가 `--env-file` 을 못 찾으면 경고만 하고 계속 가므로, 증상이 "엔진을 띄우지
    #    못했습니다" 로만 보입니다. 없는 것은 `.env` 라고 여기서 말합니다 (커밋 대상이 아니라
    #    새 체크아웃에는 없는 것이 정상입니다 - infra/README.md).
    if not ENV_FILE.exists():
        warn(f"{ENV_FILE} 이 없습니다. `cp infra/.env.example infra/.env` 후 값을 채우세요.")
        return 1

    compose = Compose(dry_run=False)

    # ⚠️ 모드를 읽으려면 컨테이너가 떠 있어야 합니다. **앞선 회차가 정지한 채 끝났을 수
    #    있고**(중단, 복구 실패), 어차피 A 이전의 정상 상태가 "엔진이 떠 있음" 입니다.
    if not compose.ready():
        warn(f"{SERVICE} 를 띄우지 못했습니다. 스택 상태부터 확인하세요.")
        warn(f"  docker compose -f {COMPOSE_FILE} ps")
        return 1

    mode = compose.generation_mode()
    # ⚠️ **읽지 못한 것을 실물 모드처럼 다루지 않습니다.** `--allow-model` 로 넘기라고 하면
    #    모드를 모르는 채로 전 구간을 돌게 되고, 배포가 실물이었다면 요금이 나갑니다.
    if mode is None:
        warn(f"{SERVICE} 에서 ADGEN_GENERATION_MODE 를 읽지 못했습니다.")
        warn("--allow-model 로 넘기지 마세요 - 모드를 모르는 채로 렌더를 사게 됩니다.")
        return 1

    # ⚠️ D 검사가 전 구간을 돌므로 실물 모드면 렌더 요금이 나갑니다. 기본은 거부이고,
    #    넘기려면 사람이 명시해야 합니다 (2026-08-24 회의 안건 02 - 상한은 코드가 아니라
    #    사람이 봅니다).
    if mode != "stub" and not args.allow_model:
        warn(f"생성 모드가 `{mode}` 입니다. D 검사가 실제 렌더를 삽니다.")
        warn("정말 돌리려면 --allow-model 을 붙이세요.")
        return 1

    print(f"스택: {mask(base_url)} / 생성 모드 {mode}\n")

    # ⚠️ 컨테이너를 만지기 **전에** 겁니다. 이 뒤로는 어떤 경로로 끝나든 `finally` 가 돌아야
    #    합니다.
    arm_signals()

    http_client = Http(base_url)
    if not sign_in(http_client, login_id, password):
        return 1

    image = product_image()
    report = Report()
    checks = (check_a_degraded, check_b_draft_timeout, check_c_render_fails, check_d_recovers)
    interrupted = False
    try:
        for check in checks:
            check(http_client, compose, report, image)
    except KeyboardInterrupt:
        warn("중단되었습니다. 복구만 하고 끝냅니다.")
        interrupted = True
    finally:
        print()
        restored = restore(compose)
        if report.sessions:
            print(f"  남긴 세션: {len(report.sessions)}건 (보존 정리 배치가 치웁니다)")
            print(f"    {', '.join(report.sessions)}")
        if not restored:
            # 복구 실패는 검사 결과보다 급합니다. 종료 코드에 실어야 스크립트를 묶어
            # 쓰는 쪽에서도 걸립니다.
            report.rows.append(("복구", "running", "실패", False))
        # ⚠️ 중단됐을 때도 씁니다. 그때까지 잰 것은 잰 것이고, 아래 머리말이 회차가 온전하지
        #    않았다는 것을 함께 적습니다 - 파일만 보고 완주한 회차로 읽히면 안 됩니다.
        if out_path is not None:
            write_record(out_path, report, mask(base_url), mode, restored, interrupted)

    if interrupted:
        return 130 if restored else 1

    print()
    if report.failures:
        print(f"실패 {report.failures}건. 기대값을 고치기 전에 왜 그런지부터 보세요.")
    else:
        print("4종 전부 통과. 결과를 05 진행 기록에 붙이세요 (언제 무엇을 확인했는가).")
    return report.failures


if __name__ == "__main__":
    raise SystemExit(main())

"""생성 지연 실측 - 잡 접수부터 결과 이미지 완료까지 (개발자_가이드 4절 첫째 행).

⚠️ **기동된 서비스에 HTTP 로만 잽니다.** `api` 나 `backend_core` 를 파이썬 import 하면 앱 간
결합 금지 규약 위반이고, 그렇게 잰 값은 배포된 서비스의 지연도 아닙니다 (`run_metrics.py` 의
같은 경고, e2e/AGENTS.md).

⚠️ **재는 구간은 렌더 잡입니다.** 지표 정의가 "잡 접수 -> 결과 이미지 완료" 이므로 세션 생성과
시안 생성은 준비 과정이고 시계는 `finalize` 응답부터 돕니다. 세션 전체 시간을 이 지표로 적으면
정의가 다른 것을 재게 됩니다.

⚠️ **`ADGEN_GENERATION_MODE=model` 이어야 합니다.** 스텁으로 재면 재는 것이 외부 API 왕복이
아니라 우리 코드의 함수 호출 시간입니다. `run-local-stack` 스킬이 model 로 바꾸지 말라고 적은
것은 화면 확인 목적의 실수 방지이고, 여기서는 그것이 측정 대상입니다.

출력은 `run_metrics.py` 가 읽는 스키마 그대로입니다 (`latencySeconds`, `messageMode`,
`outputType`). 채점은 그쪽이 합니다 - 여기서 백분위를 다시 계산하지 마세요.

    python run_latency.py --rounds 20 --dry-run
    python run_latency.py --rounds 20 --yes
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

# httpx 입니다. requests 는 이 레포의 .venv 에 없습니다 (openai 가 httpx 를 끌고 옵니다).
import httpx

BASE = "http://127.0.0.1:8000"
IMAGE = Path(
    "/mnt/wsl_data/kdt/projects/part4-adcraft-ai/outputs/API_이미지생성_검증/제품컷_입력/product-01.png"
)
"""짧은 변이 512px 이상이어야 합니다 - 아니면 세션 생성이 422 INVALID_IMAGE 로 끊깁니다."""

BRIEF = {
    "outputType": "single_ad",
    "productName": "3겹 도톰 물티슈",
    "sellingPoint": "한 장으로 충분히 닦입니다",
    # ⚠️ `note` 를 두텁게 둔 것은 의도입니다. 카테고리와 타겟이 텍스트만으로 갈리지 않으면
    #    `brief:fill` 이 `needsInput` 으로 돌아오고, 그때마다 보정 요청이 한 번 더 나갑니다.
    #    재는 것은 렌더 잡이지 브리프 문답이 아니므로, 그 변동을 앞단에서 없앱니다.
    "note": "아이를 키우는 30대 부모가 주로 사는 유아용 물티슈입니다",
}
CLARIFY = {"category": "생활용품", "target": "30대 부모"}
"""브리프가 `brief_ready` 로 넘어가지 못했을 때 한 번만 보내는 보정입니다.

⚠️ **`note` 가 아니라 `category` 와 `target` 을 직접 채웁니다.** 계약이 갈라 놓았습니다 -
`needsInput` 이면 `note` 를 채워 재추론을 돌리지만, `messageMode: degraded` 는 엔진이 아예
못 돈 것이라 재추론할 상대가 없고 사용자가 두 값을 직접 넣어야 합니다. `note` 만 보내면
`brief_filling` 에 그대로 남습니다 (2026-08-25 실측).

⚠️ 이 보정은 모델을 부르지 않으므로 요금이 없고, 재는 구간(렌더 잡) 밖입니다."""
POLL_FALLBACK_S = 3.0
GIVE_UP_S = 400.0
"""호출자 상한(300초)보다 넉넉히 둡니다. 여기서 먼저 포기하면 서비스가 얼마나 걸렸는지가
아니라 우리가 얼마나 기다렸는지를 재게 됩니다."""


def login(session: httpx.Client, login_id: str, password: str) -> None:
    """로그인하고 세션 쿠키를 **헤더로 고정**합니다.

    ⚠️ 쿠키에 `Secure` 가 붙어 있고 (`api/routes/auth.py` 의 `_COOKIE_ATTRS`, 설정으로 끌 수
    없습니다) 여기는 평문 HTTP 라, httpx 의 쿠키 저장소는 규격대로 그 쿠키를 다시 보내지
    않습니다. 브라우저가 되는 것은 `127.0.0.0/8` 을 신뢰 출처로 보는 **브라우저 쪽 예외**이지
    쿠키 규격이 아닙니다. 증상이 "로그인은 200 인데 다음 요청이 401" 이라 인증 결함으로
    오진하기 쉽습니다 - 서버가 아니라 클라이언트가 안 보낸 것입니다.
    """
    response = session.post(
        f"{BASE}/v1/auth/login", json={"loginId": login_id, "password": password}, timeout=15
    )
    response.raise_for_status()
    jar = "; ".join(f"{name}={value}" for name, value in response.cookies.items())
    if not jar:
        raise RuntimeError("로그인 응답에 쿠키가 없습니다. 계정 설정을 확인하세요")
    session.headers["Cookie"] = jar


def one_round(session: httpx.Client) -> dict[str, Any]:
    with IMAGE.open("rb") as handle:
        created = session.post(
            f"{BASE}/v1/sessions",
            data=BRIEF,
            files={"productImage": (IMAGE.name, handle, "image/png")},
            timeout=60,
        )
    if created.status_code != 201:
        return {"error": f"sessions {created.status_code}: {created.text[:160]}"}
    body = created.json()
    session_id = body["sessionId"]
    # 열화는 세션 단위 값이고 한 번 degraded 면 끝까지 degraded 입니다 (ADR-0005).
    record: dict[str, Any] = {
        "sessionId": session_id,
        "outputType": BRIEF["outputType"],
        "messageMode": body.get("messageMode"),
        "state": body.get("state"),
    }

    if body.get("state") != "brief_ready":
        # 추론이 판단하지 못했거나(needsInput) 엔진이 못 돌았습니다(degraded). 둘 다 여기서
        # 한 번 보정합니다 - 계약이 재추론을 1회로 정해 두었습니다.
        patched = session.patch(
            f"{BASE}/v1/sessions/{session_id}/brief",
            json={"revision": body.get("revision", 1), "patch": dict(CLARIFY)},
            timeout=60,
        )
        if patched.status_code >= 400:
            record["error"] = f"brief {patched.status_code}: {patched.text[:160]}"
            return record
        record["state"] = patched.json().get("state")
        record["clarified"] = True
        if record["state"] != "brief_ready":
            # 여기서 멈추지 않으면 다음 요청이 409 로 떨어지고, 원인이 상태가 아니라
            # 시안 생성인 것처럼 기록됩니다.
            record["error"] = f"보정 뒤에도 {record['state']} 입니다"
            return record

    drafted = session.post(f"{BASE}/v1/sessions/{session_id}/draft", timeout=120)
    if drafted.status_code >= 400:
        record["error"] = f"draft {drafted.status_code}: {drafted.text[:160]}"
        return record

    # 시계는 여기서부터입니다. 잡을 접수한 시각이 지표 정의의 시작점입니다.
    started = time.monotonic()
    finalized = session.post(f"{BASE}/v1/sessions/{session_id}/finalize", timeout=60)
    if finalized.status_code >= 400:
        record["error"] = f"finalize {finalized.status_code}: {finalized.text[:160]}"
        return record
    job_id = finalized.json()["jobId"]

    while True:
        polled = session.get(f"{BASE}/v1/jobs/{job_id}", timeout=30)
        if polled.status_code >= 400:
            record["error"] = f"job {polled.status_code}: {polled.text[:160]}"
            return record
        job = polled.json()
        # 계약의 값은 `done` 입니다. `completed` 가 아닙니다 (용어_사전 1.4절).
        if job["status"] in ("done", "failed"):
            record["jobStatus"] = job["status"]
            if job["status"] == "done":
                record["latencySeconds"] = round(time.monotonic() - started, 2)
            else:
                record["error"] = f"job failed: {json.dumps(job.get('error'), ensure_ascii=False)}"
            return record
        if time.monotonic() - started > GIVE_UP_S:
            record["error"] = f"{GIVE_UP_S:.0f}초를 넘겨 관측을 포기했습니다 (잡은 아직 {job['status']})"
            return record
        time.sleep(float(polled.headers.get("retry-after", POLL_FALLBACK_S)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--login-id", default="lat1")
    parser.add_argument("--password", default="lat-pass-1")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    health = httpx.get(f"{BASE}/health", timeout=10)
    health.raise_for_status()
    print(f"backend 살아 있음. {args.rounds}회차 예정 (단일 광고형, 세션당 약 0.035 USD)")
    if not IMAGE.exists():
        parser.error(f"제품 사진이 없습니다: {IMAGE}")
    if args.dry_run:
        return 0
    if not args.yes:
        parser.error("--yes 없이는 돌리지 않습니다 (실물 모드면 요금이 나갑니다)")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = args.out or Path(__file__).parent / "runs" / f"latency_{run_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    session = httpx.Client(follow_redirects=True)
    login(session, args.login_id, args.password)
    done = 0
    with out.open("w", encoding="utf-8") as handle:
        for r in range(1, args.rounds + 1):
            row = {"runId": run_id, "round": r, **one_round(session)}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()  # 중간에 죽어도 그때까지 산 회차는 남습니다
            if "latencySeconds" in row:
                done += 1
            print(f"[{r}/{args.rounds}] {row.get('latencySeconds', row.get('error', '?'))}")

    print(f"\n{out}\n완료 {done}/{args.rounds}")
    print(f"  python eval/run_metrics.py --input {out}    # 백분위는 그쪽이 냅니다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

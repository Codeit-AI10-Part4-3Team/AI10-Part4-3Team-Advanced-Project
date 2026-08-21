---
name: run-local-stack
description: 로컬에서 이 서비스를 띄우고 화면을 확인합니다 (vite 5173 + backend 8000 + ai-engine 8100). 앱을 실행/기동/스크린샷하거나, 변경이 실제 화면에서 도는지 확인할 때 씁니다. Docker 없이 uvicorn 과 vite 로 직접 띄우며 생성은 스텁 모드라 외부 API 를 부르지 않습니다.
---

# 로컬 스택 기동

브라우저가 보는 것은 **5173 하나**입니다. `/v1` 은 vite 개발 서버가 8000 으로 프록시합니다
(`apps/frontend/vite.config.ts`). 세션 쿠키가 `Secure` + `SameSite=Lax` 라 출처가 갈리면 로그인이
성립하지 않기 때문이며, 배포에서는 nginx 가 같은 일을 합니다 (`apps/frontend/nginx.conf`).

| 포트 | 프로세스 |
|---|---|
| 5173 | vite 개발 서버 (프론트, `/v1` 프록시) |
| 8000 | backend (`api.main:app`) |
| 8100 | ai-engine (`ai_engine.service:app`) |

`infra/docker-compose.yml` 로도 뜨지만 Docker 가 없는 환경에서는 아래가 유일한 경로입니다.

## 0. 사전 준비

```bash
# 파이썬: 레포 루트 .venv (conda `ai` 아님 - CLAUDE.md 의 인터프리터 함정)
python3 -c "import ai_engine, backend_core; print(ai_engine.__file__)"   # 이 레포 경로여야 정상

# Node 22. Dockerfile 이 node:22-slim 이고 package.json engines 가 >=22.13 이라 최신판이 아니라 22.
brew install node@22
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"    # ⚠️ keg-only 라 PATH 에 직접 넣어야 합니다
corepack enable                                       # pnpm 은 packageManager 핀(11.19.0)을 따라갑니다

cd apps/frontend && pnpm install --frozen-lockfile
```

## 1. 로컬 환경 파일

로그인에는 시드 계정이 필요합니다. 가입이 501 이라 계정이 들어오는 경로는 설정뿐입니다 (ADR-0008).

```bash
REPO=$(git rev-parse --show-toplevel)
mkdir -p "$REPO/data/images"

"$REPO/.venv/bin/python" - "$REPO" <<'PY'
import json, secrets, sys, pathlib, shlex
from argon2 import PasswordHasher
ph = PasswordHasher()
accounts = [{"login_id": "demo1", "password_hash": ph.hash("demo-pass-1")},
            {"login_id": "demo2", "password_hash": ph.hash("demo-pass-2")}]
env = {
    "ADGEN_SESSION_SECRET": secrets.token_urlsafe(32),
    # ⚠️ 공백 없는 compact JSON. 아래 인용과 한 쌍입니다.
    "ADGEN_ACCOUNTS": json.dumps(accounts, ensure_ascii=False, separators=(",", ":")),
    "ADGEN_GENERATION_MODE": "stub",
    # ⚠️ 절대경로. 기본값은 cwd 상대라 apps/backend 에서 띄우면 apps/backend/data/ 에 떨어지는데
    #    그 경로는 gitignore 대상이 아닙니다. 루트 data/ 만 무시됩니다.
    "ADGEN_DB_PATH": f"{sys.argv[1]}/data/adgen.sqlite",
    "ADGEN_IMAGE_DIR": f"{sys.argv[1]}/data/images",
}
p = pathlib.Path(sys.argv[1]) / "data" / "run.env"
p.write_text("\n".join(f"{k}={shlex.quote(v)}" for k, v in env.items()) + "\n", encoding="utf-8")
print("계정: demo1 / demo-pass-1,  demo2 / demo-pass-2")
PY
```

**⚠️ `shlex.quote` 를 빼지 마세요.** `set -a; . run.env` 로 읽는데, `ADGEN_ACCOUNTS` 의 JSON 에
공백이 있으면 셸이 거기서 값을 자릅니다. 증상은 파일이 깨진 것이 아니라 **로그인만
`INVALID_CREDENTIALS` 로 실패**하는 것이라 원인을 찾기 어렵습니다 (실측 사고 있음).

**⚠️ `infra/.env` 를 건드리지 마세요.** 그 파일은 compose 용이고 `$` 이스케이프 규칙이 다릅니다
(`infra/README.md`). 위 파일은 uvicorn 에 직접 넘기는 별개 파일입니다.

## 2. 기동

세 개를 각각 백그라운드로 띄웁니다. 순서는 ai-engine 먼저입니다.

```bash
REPO=$(git rev-parse --show-toplevel)
cd "$REPO/apps/ai-engine" && set -a && . "$REPO/data/run.env" && set +a && \
  "$REPO/.venv/bin/uvicorn" ai_engine.service:app --host 127.0.0.1 --port 8100 --log-level warning &

cd "$REPO/apps/backend" && set -a && . "$REPO/data/run.env" && set +a && \
  "$REPO/.venv/bin/uvicorn" api.main:app --host 127.0.0.1 --port 8000 --log-level warning &

export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
cd "$REPO/apps/frontend" && pnpm dev --host 127.0.0.1 &
```

`depends_on` 이 없으므로 backend 가 늦게 떠도 화면은 뜹니다. 그때 사용자가 보는 것은 502 가
아니라 화면이 만든 "서버에 연결하지 못했습니다" 입니다.

## 3. 떴는지 확인

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/health   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5173/         # 200
```

**프록시가 사는지는 5173 으로만 확인합니다.** 브라우저가 보는 것이 그것뿐이기 때문입니다.

```bash
J=$(mktemp)
curl -s -c "$J" -X POST http://127.0.0.1:5173/v1/auth/login \
  -H 'content-type: application/json' -d '{"loginId":"demo1","password":"demo-pass-1"}'
curl -s -b "$J" http://127.0.0.1:5173/v1/me      # 같은 userId 가 나오면 쿠키 왕복이 정상
```

`http://127.0.0.1:5173/v1/health` 가 **JSON 404** 를 주면 프록시가 도는 것입니다 - backend 의
health 는 `/health` 이지 `/v1/health` 가 아닙니다. HTML 이 오면 프록시를 안 타고 SPA 폴백에
떨어진 것입니다.

## 4. 화면 확인

브라우저에서 **http://127.0.0.1:5173**, 계정은 `demo1` / `demo-pass-1`.

무인 확인이 필요하면 Playwright 로 몰아 봅니다. **레포 밖에 설치하세요** - `apps/frontend` 에
넣으면 `package.json` 과 lockfile 이 바뀝니다.

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
D=$(mktemp -d) && cd "$D" && echo '{"name":"shot","private":true}' > package.json
npm i -D playwright@latest --silent && npx playwright install chromium
```

```js
// shot.mjs — 로그인까지 몰고 스크린샷 두 장
import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
p.on("pageerror", e => console.log("pageerror:", e.message));
await p.goto("http://127.0.0.1:5173/", { waitUntil: "networkidle" });
console.log("URL:", p.url());                       // /login 으로 튕기면 RequireAuth 가 도는 것
await p.screenshot({ path: "01-login.png" });
await p.fill('input[name="loginId"]', "demo1");
await p.fill('input[name="password"]', "demo-pass-1");
await p.click('button[type="submit"]');
await p.waitForURL("**/", { timeout: 15000 }).catch(() => {});
await p.waitForTimeout(1200);
await p.screenshot({ path: "02-studio.png", fullPage: true });
console.log("body chars:", (await p.textContent("body") || "").trim().length);  // 0 이면 기동 실패
await b.close();
```

**스크린샷을 눈으로 보세요.** SPA 는 런타임 오류가 나도 HTTP 200 + 빈 화면이라 `curl` 로는
구분되지 않습니다.

콘솔의 `GET /v1/me` 401 두 건은 정상입니다 - 로그인 전 세션 확인이고, 두 번인 것은 개발 모드
StrictMode 의 effect 이중 실행입니다.

## 5. 관통 스모크 (선택)

화면 없이 계약만 두드릴 때. **`outputType` 은 `single_ad` 입니다** - `single` 을 보내면 422
`INVALID_REQUEST` 가 돌아옵니다 (계약의 enum 은 `comic` 과 `single_ad`).

```bash
J=$(mktemp); B=http://127.0.0.1:8000
curl -s -c "$J" -X POST "$B/v1/auth/login" -H 'content-type: application/json' \
  -d '{"loginId":"demo1","password":"demo-pass-1"}' > /dev/null

# 제품 사진은 짧은 변 512px 이상이어야 합니다 (422 INVALID_IMAGE 방지)
SID=$(curl -s -b "$J" -X POST "$B/v1/sessions" \
  -F 'outputType=single_ad' -F "productImage=@product.png;type=image/png" \
  -F 'productName=테스트 제품' -F 'sellingPoint=테스트 소구점' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["sessionId"])')

curl -s -b "$J" -X POST "$B/v1/sessions/$SID/draft" > /dev/null
JID=$(curl -s -b "$J" -X POST "$B/v1/sessions/$SID/finalize" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["jobId"])')
curl -s -b "$J" -D - "$B/v1/jobs/$JID" -o /dev/null | grep -i retry-after   # queued 면 3
```

정상 결과: 시안 카피에 `[STUB]` 접두사, 결과 이미지 `image/webp` 약 5.7KB, 확정 재시도는
409 `STATE_CONFLICT` (INV-3).

## 6. 종료

```bash
pkill -f "vite"
pkill -f "uvicorn api.main:app"
pkill -f "uvicorn ai_engine.service:app"
```

## 하지 말 것

- **`ADGEN_GENERATION_MODE` 를 `model` 로 바꾸지 마세요.** 화면 확인이 목적이면 스텁으로 충분하고,
  실물 모드는 외부 API 를 실제로 부릅니다. 남은 예산이 유한합니다 (ADR-0017).
- **스텁 출력을 측정값으로 보고하지 마세요.** `[STUB]` 접두사가 그 표시입니다.
- **`apps/frontend/dist` 를 그대로 믿지 마세요.** gitignore 대상이라 오래된 빌드가 남아 있을 수
  있습니다. 화면을 확인할 때는 `pnpm dev` 를 쓰거나 `pnpm build` 를 먼저 돌리세요.

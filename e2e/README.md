# e2e — 앱을 가로지르는 종단 관통 테스트

담당: QA 역할. 역할 정의는 [docs/역할_가이드/](../docs/역할_가이드/)를 보세요.

## 왜 앱 밖에 있는가

검증 대상이 **프론트 → backend → ai-engine → 응답** 전 구간이라 특정 앱의 소유가 아닙니다.
`apps/*/tests/`에 두면 required 상태 체크(`Unit tests (backend/ai-engine)`)가 이 테스트를
수집하는데, E2E는 **서비스 기동과 외부 API 키**를 요구하므로 그 순간 모든 PR이 블록됩니다.
그래서 별도 최상위 디렉토리 + **non-required 워크플로**([`.github/workflows/e2e.yml`](../.github/workflows/e2e.yml)) 조합입니다.

- ❌ 여기서 `api` / `backend_core` / `ai_engine` 을 **파이썬 import 하지 마세요.**
  앱 간 결합 금지 규약이 그대로 적용됩니다 — 관통 검증은 **기동된 서비스에 HTTP로만** 합니다.
- ❌ 가드레일을 끄거나 목(mock)으로 대체해 통과시키지 마세요. on/off 델타는 보고 지표입니다.

## 실행

```bash
pip install -r e2e/requirements.txt
playwright install chromium                 # 브라우저 시나리오를 쓸 때만

# 계정을 시드해 스택을 띄웁니다 (아래 "계정이 필요한 이유")
export ADGEN_SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export ADGEN_ACCOUNTS='[{"login_id":"e2e1","password_hash":"$argon2id$..."}, {"login_id":"e2e2","password_hash":"$argon2id$..."}]'
docker compose -f infra/docker-compose.yml up -d --wait --build

# 둘 다 앞단 프록시입니다 (ADR-0016). backend 의 8000 은 더 이상 호스트에 게시되지 않습니다.
export E2E_BASE_URL=http://localhost        # API 가 답하는 곳
export E2E_WEB_URL=http://localhost         # 브라우저가 보는 곳
export E2E_LOGIN_ID=e2e1        E2E_PASSWORD=...
export E2E_OTHER_LOGIN_ID=e2e2  E2E_OTHER_PASSWORD=...
cd e2e && pytest -v      # ⚠️ cwd가 e2e여야 pyproject.toml의 testpaths/markers를 집습니다
```

> ⚠️ **`--build` 를 빼면 이전에 빌드된 이미지가 그대로 뜹니다.** `up -d` 는 이미지가 있으면
> 다시 빌드하지 않으므로, 화면을 고치고 돌리면 **옛날 프론트엔드**를 상대로 테스트하게 됩니다
> (실측: 2026-08-19에 이미 지운 mock 화면이 떠서 브라우저 테스트가 실패했습니다).
> CI 는 러너가 매번 비어 있어 이 문제가 없습니다.

### 배포된 VM 을 상대로 돌리기

위는 로컬에서 스택을 직접 띄우는 경우입니다. **배포된 VM 을 상대로 돌릴 때는 다른 함정이 있습니다**
(2026-08-21 에 처음 해 봤습니다. F17 소관은 05 입니다 -- [구현_범위.md](../docs/공통_가이드/구현_범위.md) 2절).

```bash
# VM 안에서. compose 를 새로 띄우지 않습니다 - 이미 떠 있는 배포를 상대합니다.
python3 -m venv ~/e2e-venv
~/e2e-venv/bin/pip install -r /srv/adcraft/app/e2e/requirements.txt
~/e2e-venv/bin/playwright install --with-deps chromium

export E2E_BASE_URL=https://<공개호스트>      # infra/.env 의 ADGEN_PUBLIC_HOST
export E2E_WEB_URL=https://<공개호스트>
export E2E_LOGIN_ID=... E2E_PASSWORD=...
export E2E_OTHER_LOGIN_ID=... E2E_OTHER_PASSWORD=...

cd /srv/adcraft/app/e2e && ~/e2e-venv/bin/pytest -v
```

⚠️ **venv 는 배포 체크아웃 밖에 만드세요.** `/srv/adcraft/app` 안에 만들면 다음 배포의 사전
점검이 "추적되지 않는 파일"로 경고합니다. `.pytest_cache` 와 `__pycache__` 는 루트
`.gitignore` 에 있어 문제되지 않습니다.

⚠️ **`--with-deps` 를 빼지 마세요.** 헤드리스 리눅스에는 chromium 이 요구하는 시스템
라이브러리가 없어서, 바이너리만 깔면 실행 시점에 `error while loading shared libraries` 로
막힙니다. `--with-deps` 는 sudo 로 apt 를 부르고 디스크를 500MB ~ 1GB 씁니다 - 이미지 재빌드
직후라면 `df -h /` 를 먼저 보세요.

⚠️ **`E2E_BASE_URL` 과 `E2E_WEB_URL` 을 빠뜨리면 전부 skip 되고 초록으로 끝납니다.**
2026-08-21 첫 실행이 정확히 그렇게 났습니다 - 계정 변수만 넣고 URL 둘을 빠뜨려 6건이 전부
skip 됐는데, 종료 코드는 0 이었습니다. **`-v` 로 skip 개수를 보는 것이 절차의 일부입니다.**

**공개 호스트 이름은 저장소에 적지 마세요.** 이 저장소는 public 이고 배포 호스트명에 외부 IP 가
들어 있습니다 ([GCP_VM_사용_가이드.md](../docs/공통_가이드/GCP_VM_사용_가이드.md) 2-b절).

> 2026-08-21 실측으로 하나 확인됐습니다. **VM 안에서 자기 공개 호스트로 붙는 것(헤어핀)이
> 됩니다** - `curl` 이 `200` 을 답합니다. 그래서 `/etc/hosts` 를 건드리거나 `--resolve` 를
> 쓸 필요가 없었습니다. 되지 않는 환경으로 옮기면 `127.0.0.1 <공개호스트>` 를 `/etc/hosts` 에
> 한 줄 넣으면 됩니다 - httpx 와 Playwright 둘 다 OS 리졸버를 쓰므로 그것으로 충분하고,
> SNI 와 Host 에는 진짜 이름이 실리므로 인증서 검증은 그대로 살아 있습니다.

### 환경변수와 skip 규칙

**아무것도 없으면 전부 skip 됩니다.** "연결은 돼 있고 대상만 아직 없는" 상태를 초록으로
유지하기 위한 설계이며, 값이 채워지는 만큼 실제 검증이 켜집니다.

| 변수 | 없으면 | 있으면 |
|---|---|---|
| `E2E_BASE_URL` | 전부 skip | HTTP 시나리오 실행 |
| `E2E_WEB_URL` | 브라우저 시나리오만 skip | 프론트엔드까지 관통 |
| `E2E_LOGIN_ID` · `E2E_PASSWORD` | 로그인이 필요한 시나리오 skip | 광고 경로 전 구간 |
| `E2E_OTHER_LOGIN_ID` · `E2E_OTHER_PASSWORD` | INV-9(남의 세션 404)만 skip | 소유권 판정까지 |

**`E2E_BASE_URL` 과 `E2E_WEB_URL` 은 지금 같은 값이지만 일부러 다른 변수입니다.**
[ADR-0016](../docs/adr/0016-HTTPS_종단_지점과_인증서_발급_경로.md) 이후 앞단 프록시 하나가
둘을 다 받으므로 값이 겹칩니다. 그래도 묻는 질문이 다릅니다 - 하나는 "API 가 어디서
답하는가", 다른 하나는 "사람이 브라우저에 무엇을 치는가"입니다. 하나로 합쳐 두면 둘이
갈라지는 날이 가려지고, **그날이 바로 로그인이 멈추는 날입니다** (08-18 배포가 정확히 그
경우였습니다 - 화면은 떴는데 쿠키가 실리지 않았습니다).

### 계정이 필요한 이유, 그리고 커밋하지 않는 이유

가입 경로가 501이라 계정은 `ADGEN_ACCOUNTS` 시드로만 들어옵니다
([ADR-0008](../docs/adr/0008-로그인_수단과_스켈레톤_범위.md)). **둘이 최소값입니다** - 하나면
"남의 세션"이 존재하지 않아 INV-9의 404 경로를 한 번도 지나지 않습니다.

**저장소는 public 이므로 해시도 평문도 커밋하지 않습니다.** CI 는 잡 안에서 임시 계정을 만들어
프로세스 환경으로 넘깁니다 (`.github/workflows/e2e.yml`의 `Seed throwaway accounts`).
GitHub secrets 로 두지 않은 이유는 fork PR 에서 값이 비어 관통 시나리오만 조용히 skip 되기
때문입니다 - 초록인데 아무것도 검증하지 않는 상태가 이 하네스가 막으려는 바로 그것입니다.

⚠️ 값을 `infra/.env` 에 적을 때는 argon2 해시의 `$` 를 `$$` 로 이스케이프하세요. compose 가
`.env` 안의 `$` 를 변수 참조로 읽어 값을 조용히 뭉갭니다 (`infra/README.md`). 위 예시처럼
**환경변수로 넘기면** 그 단계를 지나가지 않습니다.

## 무엇이 들어 있나

| 파일 | 무엇을 지키나 |
|---|---|
| `tests/test_harness.py` | 하네스 배선 자체. `/health` 와 계약 오류 형태뿐입니다 |
| `tests/test_ad_flow.py` | **광고 경로 관통** (HTTP). 입력 -> 브리프 -> 시안 -> 확정 -> 폴링 -> 결과. 그리고 INV-9(남의 세션 404)와 미인증 401 |
| `tests/test_browser_flow.py` | **브라우저 관통.** 로그인부터 파일 다운로드까지. 구현_범위 1절의 전체 DoD 문장 그대로 |

⚠️ **`test_harness.py` 가 초록이라고 관통이 검증된 것이 아닙니다.** 그 파일은 스택이 떴는지만
봅니다. 2026-08-19 이전에는 그마저도 템플릿 질의응답(`/v1/ask`)을 지나고 있어서 광고 경로와 한 줄도
겹치지 않았고, 그 상태로 "종단 관통 테스트 통과" 였습니다 - 루트 `AGENTS.md` 가 말하는
"게이트 통과 != 관통 경로 검증" 의 실제 사례입니다. 그 경로는 이제 삭제되었습니다
(API_계약.md 7절).

관통 경로는 **단일 광고형 하나**입니다 (구현_범위 1절). 만화형은 분기만 둔 스텁이므로 통과를
요구하지 않습니다 - 요구하면 스텁의 현재 동작이 계약으로 굳습니다.

### 아직 자동화하지 않은 것

- **열화 경로**(ai-engine 정지 -> 201 + `brief_filling` + `degraded`)는 컨테이너를 죽였다
  살리는 조작이 필요해 넣지 않았습니다. 2026-08-19에 05가 손으로 쟀습니다
  ([05 일정](../docs/역할_일정/05-백엔드_인프라.md)). 넣는다면 이 하네스가 docker 를 직접
  다루게 되므로, 그 결합을 감수할지가 먼저 정해져야 합니다.
- **가드레일 거절**(`CONTENT_POLICY_REJECTED`)은 스텁이 거절하지 않아 재현할 조건이 없습니다.
  실물 이음매가 붙은 뒤에 들어갈 자리입니다.

**첫 항목은 하네스 밖에서 잽니다** (2026-08-28) -- `scripts/check_failure_modes.py` 가 열화,
시안 타임아웃, 렌더 실패, 복구 넷을 도는 스택에 대고 확인합니다. **위의 "먼저 정해져야
합니다" 를 열지 않으려고 일부러 하네스 밖에 두었습니다.** 그 결합을 감수하기로 정해지면 그때
이 파일들 옆으로 옮기는 것이 맞고, 그 전까지 여기에는 docker 를 부르는 코드가 없습니다.

⚠️ 그 스크립트는 CI 가 돌리지 않습니다. `종단 관통 테스트` 가 초록인 것과 실패 모드가
확인된 것은 여전히 다른 말입니다.

## 작성 규칙

- **실패 모드가 본체입니다.** 성공 경로만이 아니라 의존 서비스 장애·권한 거부·모델 이탈에서
  안전장치가 동작하는지를 검사하세요 (`@pytest.mark.failure`).
- **외부 유료 API 호출은 최소화.** 관통 확인에 필요한 최소 횟수만. 반복 채점은
  [`apps/ai-engine/eval/`](../apps/ai-engine/eval/) 하네스의 몫입니다.
- 마커는 `e2e/pyproject.toml`에 정의돼 있습니다 (`flow` / `failure`). 새 축이 필요하면
  거기에 먼저 등록하세요 — 미등록 마커는 조용히 오타로 남습니다.

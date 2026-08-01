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
playwright install --with-deps chromium     # 브라우저 시나리오를 쓸 때만

# 스택 기동 후
docker compose -f infra/docker-compose.yml up -d --wait
export E2E_BASE_URL=http://localhost:8000
cd e2e && pytest -v      # ⚠️ cwd가 e2e여야 pyproject.toml의 testpaths/markers를 집습니다
```

`E2E_BASE_URL`이 없으면 **모든 테스트가 skip** 됩니다. 하네스가 "연결은 돼 있고 대상만 아직
없는" 상태를 초록으로 유지하기 위한 설계이며, 스택이 뜨면 자동으로 실제 검증에 들어갑니다.

## 작성 규칙

- **실패 모드가 본체입니다.** 성공 경로만이 아니라 의존 서비스 장애·권한 거부·모델 이탈에서
  안전장치가 동작하는지를 검사하세요 (`@pytest.mark.failure`).
- **외부 유료 API 호출은 최소화.** 관통 확인에 필요한 최소 횟수만. 반복 채점은
  [`apps/ai-engine/eval/`](../apps/ai-engine/eval/) 하네스의 몫입니다.
- 마커는 `e2e/pyproject.toml`에 정의돼 있습니다 (`flow` / `failure`). 새 축이 필요하면
  거기에 먼저 등록하세요 — 미등록 마커는 조용히 오타로 남습니다.

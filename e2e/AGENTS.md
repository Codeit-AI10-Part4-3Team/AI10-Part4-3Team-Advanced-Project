# e2e — 디렉토리 규칙

루트 [/AGENTS.md](../AGENTS.md)가 전역 정본입니다.

- **HTTP 전용입니다.** 여기서 앱 패키지를 import하면 앱과 동일한 경계 규칙을 어기는 것입니다.
- **E2E를 `apps/*/tests/`로 옮기지 마세요.** 그 경로는 *required* pytest 매트릭스로 들어가는데,
  E2E는 스택 기동과 외부 키가 필요하므로 required가 되는 순간 모든 PR이 인프라 사정으로 막힙니다.
- 이 폴더의 CI는 의도적으로 **non-required**입니다 — required로 승격하자는 제안을 코드로 옮기지 마세요.
- 실행: 스택 기동 후 `cd e2e && pytest`. `run-tests.sh` 대상이 아니며,
  **게이트 통과 ≠ 관통 경로 검증**입니다.

# apps/frontend — 디렉토리 규칙

루트 [/AGENTS.md](../../AGENTS.md)가 전역 정본입니다. **스캐폴딩은 끝났습니다** —
React 19 + Vite + TypeScript, 패키지 매니저는 pnpm (2026-08-13). 로그인(2026-08-15)과
`S7`·`S8` 관통(2026-08-19)까지 들어와, 화면에 보이는 값은 전부 `apps/backend` 응답입니다.
현재 범위와 다음 순서는 이 폴더의 [README.md](README.md).

- **진행 상태를 화면이 보관하지 않습니다.** `sessionId`는 URL, `jobId`는 세션에 있어 새로고침과
  재접속으로 복원됩니다. 화면에 상태를 들면 그 성질이 사라집니다.
- **폴링 간격은 `Retry-After`를 따릅니다.** 하드코딩한 상수는 헤더가 없을 때의 하한뿐입니다 —
  서버가 큐 부하에 따라 클라이언트를 늦출 수 있어야 하기 때문입니다.
- **화풍 후보를 화면에 지어내지 마세요.** 후보 목록이 미정이고(미결정_대장 A-3) 값은
  `GET /v1/art-styles`에서만 옵니다. 지어낸 값이 브리프에 저장되면 출처를 알 수 없게 됩니다.
- **`needsInput`과 `degraded`는 오류가 아닙니다.** 오류 화면으로 보내면 설계된 열화가
  장애로 보고됩니다 ([ADR-0005](../../docs/adr/0005-열화_폴백은_자동화_생략으로_한정.md)).

- **경로 이름은 반드시 영어.** 빌드 도구 · import 경로 · Docker/CI가 소비하므로 한글 세그먼트는
  판단 대상이 아니라 결함입니다. 문서 폴더의 한글 규약은 여기 적용되지 않습니다.
- **루트 `.gitignore`의 `/lib/` · `/build/` · `/dist/` 앵커를 지우지 마세요.** 선행 슬래시를
  없애면 `apps/frontend/src/lib/`(SvelteKit · Next 관용 경로)가 통째로 무시되어 소스가 조용히
  사라집니다. git은 무시된 디렉토리 안의 파일을 살려내지 못합니다.
- **프론트 CI를 required로 지정하지 마세요.** [`frontend-ci.yml`](../../.github/workflows/frontend-ci.yml)
  에는 `paths:` 필터가 걸려 있어, required가 되는 순간 프론트를 건드리지 않은 모든 PR이
  "Expected"로 영구 대기합니다. `package.json`이 생겨 이 워크플로는 이미 활성 상태입니다.
- **호출 대상은 `apps/backend`뿐입니다.** 스펙의 단일 원천은
  [`packages/contracts/openapi.yaml`](../../packages/contracts/openapi.yaml)이고 필드는 camelCase입니다.
  스펙에 없는 필드를 프론트에서 먼저 쓰기 시작하면 그때부터 계약이 아니라 구두 합의입니다.

## 스캐폴딩과 함께 끝난 것 (되돌리지 마세요)

- `frontend-ci.yml`의 install 단계와 cache 설정은 **pnpm 기준으로 교체**되었습니다.
- `.github/dependabot.yml`의 npm 블록(`/apps/frontend`)은 **주석 해제**되어 돌고 있습니다.
- `frontend-ci.yml`의 스캐폴딩 가드(`if: hashFiles(...)`, `--if-present`)는 **제거**되었습니다.
  다시 넣으면 스크립트가 사라지거나 이름이 바뀐 뒤에도 잡이 조용히 초록으로 통과합니다 —
  "아직 없어서 건너뜀"과 "없어져서 검사 안 됨"이 CI에서 구분되지 않습니다.

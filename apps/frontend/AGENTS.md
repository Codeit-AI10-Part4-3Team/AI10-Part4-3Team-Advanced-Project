# apps/frontend — 디렉토리 규칙

루트 [/AGENTS.md](../../AGENTS.md)가 전역 정본입니다. **아직 스캐폴딩 전**이며, 프레임워크는
프로젝트가 정합니다. 스캐폴딩 절차와 배경은 이 폴더의 [README.md](README.md).

- **경로 이름은 반드시 영어.** 빌드 도구 · import 경로 · Docker/CI가 소비하므로 한글 세그먼트는
  판단 대상이 아니라 결함입니다. 문서 폴더의 한글 규약은 여기 적용되지 않습니다.
- **루트 `.gitignore`의 `/lib/` · `/build/` · `/dist/` 앵커를 지우지 마세요.** 선행 슬래시를
  없애면 `apps/frontend/src/lib/`(SvelteKit · Next 관용 경로)가 통째로 무시되어 소스가 조용히
  사라집니다. git은 무시된 디렉토리 안의 파일을 살려내지 못합니다.
- **프론트 CI를 required로 지정하지 마세요.** [`frontend-ci.yml`](../../.github/workflows/frontend-ci.yml)
  에는 `paths:` 필터가 걸려 있어, required가 되는 순간 프론트를 건드리지 않은 모든 PR이
  "Expected"로 영구 대기합니다. 이 워크플로는 `package.json`이 생기면 자동으로 활성화됩니다.
- **호출 대상은 `apps/backend`뿐입니다.** 스펙의 단일 원천은
  [`packages/contracts/openapi.yaml`](../../packages/contracts/openapi.yaml)이고 필드는 camelCase입니다.
  스펙에 없는 필드를 프론트에서 먼저 쓰기 시작하면 그때부터 계약이 아니라 구두 합의입니다.

## 스캐폴딩 시 함께 고칠 것

- npm이 아닌 패키지 매니저(pnpm · yarn)를 쓴다면 `frontend-ci.yml`의 install 단계와 cache 설정을
  같은 PR에서 교체합니다.
- `.github/dependabot.yml`의 npm 블록은 주석 처리되어 있습니다. `package.json`이 생긴 뒤에
  해제하세요 — 없는 디렉토리를 등록하면 매주 파싱 오류가 쌓입니다.

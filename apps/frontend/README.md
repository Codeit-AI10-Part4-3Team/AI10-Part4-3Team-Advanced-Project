# apps/frontend

프론트엔드 자리입니다. **아직 스캐폴딩 전**입니다 — 프레임워크는 프로젝트가 정합니다
(Next.js / SvelteKit / Vite+React 등).

## 스캐폴딩 전에 읽을 것

- **경로 이름은 반드시 영어.** 빌드 도구·import 경로·Docker/CI가 소비하는 경로라 한글 세그먼트는
  인코딩·이식성 문제를 만듭니다 (AGENTS.md 명명 규약).
- ⚠️ **루트 `.gitignore`의 함정**: `lib/`·`build/`·`dist/` 는 **루트 기준(`/lib/`)으로만** 무시하도록
  앵커돼 있습니다. 선행 슬래시를 지우면 `apps/frontend/src/lib/`(SvelteKit·Next 관용 경로)가
  통째로 무시돼 소스가 조용히 사라집니다. 그 줄을 건드리지 마세요.
- **CI는 별도 워크플로**입니다 ([`.github/workflows/frontend-ci.yml`](../../.github/workflows/frontend-ci.yml)) —
  `package.json`이 생기는 순간 자동으로 활성화됩니다. ⚠️ paths 필터가 걸려 있으므로
  **required status check로 지정하지 마세요** (해당 경로 변경이 없는 PR이 영구 블록됩니다).
- npm이 아닌 패키지 매니저(pnpm/yarn)를 쓴다면 그 워크플로의 install 단계와 cache 설정을
  함께 교체하세요.
- **Dependabot**: `.github/dependabot.yml`의 npm 블록은 주석 처리돼 있습니다. `package.json`이
  생긴 뒤 주석을 해제하세요 (없는 디렉토리를 등록하면 매주 파싱 오류가 쌓입니다).

## 백엔드 계약

호출 대상은 `apps/backend`뿐입니다. 스펙은 [`packages/contracts/openapi.yaml`](../../packages/contracts/openapi.yaml)이
단일 원천이며, 필드는 camelCase입니다. 스펙에 없는 필드를 프론트에서 먼저 쓰기 시작하면
그때부터 계약이 아니라 구두 합의가 됩니다.

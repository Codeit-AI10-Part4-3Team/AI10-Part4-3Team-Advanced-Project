# apps/frontend — 행복한 3팀 프론트엔드

제품 이미지와 정보를 입력하면 브랜드 스타일의 광고 이미지 또는 6컷 광고 만화를 만드는 서비스의
프론트엔드 스캐폴딩입니다. 현재 목표는 완성형 화면이 아니라, Figma 참고 시안의 기능을 실제 백엔드
계약에 맞춰 안전하게 확장할 수 있는 뼈대를 만드는 것입니다.

> API의 단일 원천은 [`packages/contracts/openapi.yaml`](../../packages/contracts/openapi.yaml)입니다.
> 이 문서와 코드가 계약과 다르면 OpenAPI가 맞습니다.

## 현재 범위

현재 포함된 것은 다음과 같습니다.

- Vite + React + TypeScript 실행 환경
- 서비스명 **행복한 3팀**과 기본 디자인 토큰
- 채팅형 세션 이력 사이드바
- `comic` / `single_ad` 출력 유형 선택
- 제품 이미지, 제품명, 소구점, 메모, 화풍 입력 폼
- 브리프 확인, 시안, 렌더 결과가 들어갈 패널
- 계약과 동일한 세션·잡 상태 타입
- 백엔드 요청을 한곳으로 모으는 API 클라이언트 경계
- 데스크톱/태블릿/모바일 반응형 레이아웃
- **라우팅과 로그인** (2026-08-15). `/login` 화면, `POST /v1/auth/login`, `GET /v1/me` 기반
  세션 확인, 로그아웃, 보호된 경로
- **광고 생성 관통** (2026-08-19, S7 · S8). 세션 목록, multipart 세션 생성, 브리프 표시,
  시안 생성, 확정, `Retry-After`를 따르는 잡 폴링, 결과 이미지 표시와 다운로드
- **브리프 수정** (2026-08-21, F5). `PATCH .../brief` 로 자동 채운 값을 고칩니다. 바뀐 키만
  보내고 `revision` 으로 낙관적 잠금을 걸며, 시안이 생기면 잠깁니다 (INV-7)
- **테스트 하네스** (2026-08-21). Vitest + Testing Library, `pnpm test`

**mock 데이터는 없습니다.** 화면에 보이는 값은 전부 `apps/backend` 응답입니다. 아직 안 된 것은
아래 "지금 화면이 못 하는 것"에 있습니다.

### 지금 화면이 못 하는 것

| 무엇 | 어디서 이어지나 |
| --- | --- |
| 시안 부분 수정 (`PATCH .../draft`) | 미연결. 브리프 수정은 F5 로 들어왔습니다 |
| 만화형 시안 생성 | 관통 경로는 단일 광고형 하나이고 만화형은 분기만 둔 스텁입니다 (구현_범위 1절). 세션은 만들어지지만 시안 생성 버튼을 두지 않습니다 |
| 화풍 목록 | `GET /v1/art-styles`가 빈 배열입니다. 후보 미정 (미결정_대장 A절 3번) |
| 오류 5종 구분 | F10 (08-26). 지금은 코드별 문구 하나에 상단 배너 하나 |

### 로그인이 먼저인 이유

계약의 보호 범위가 `/health`와 `/v1/auth/*`를 뺀 **모든 `/v1` 경로**입니다 (API_계약 6절).
세션 생성을 먼저 붙이면 첫 요청이 401이고, 그때 화면이 할 수 있는 일이 없습니다 -- 로그인 없이
붙일 수 있는 경로가 아예 없으므로 순서가 선택지가 아닙니다.

### 토큰을 저장하지 않습니다

`localStorage`도 `sessionStorage`도 쓰지 않습니다. 세션 토큰은 `HttpOnly` 쿠키이고(ADR-0013)
스크립트가 읽을 수 없으며, 그것이 XSS 한 번에 토큰이 새지 않는 이유입니다. "로그인했는가"의 답은
화면이 들고 있는 값이 아니라 `GET /v1/me`의 응답입니다.

## 기술 선택

| 영역 | 선택 | 이유 |
| --- | --- | --- |
| UI | React 19 | 화면을 기능 단위 컴포넌트로 분리하기 쉽고 팀 채용/학습 자료가 많음 |
| 빌드 | Vite 8 | 별도 SSR 요구가 확정되지 않은 생성 도구형 SPA에 필요한 구성이 단순함 |
| 언어 | TypeScript | OpenAPI의 camelCase 계약과 상태 유니언을 컴파일 단계에서 검증 |
| 패키지 매니저 | pnpm | 모노레포 확장 시 저장 공간과 설치 속도에 유리하고 lockfile 재현 가능 |
| 스타일 | CSS 변수 + 일반 CSS | 초기 스캐폴딩에서 디자인 시스템 의존성을 먼저 고정하지 않음 |

나머지 도구는 기능 구현 시점에 추가합니다. 들어온 것은 아래에 표시합니다.

- 라우팅: React Router — **도입됨** (로그인과 보호된 경로, 2026-08-15)
- 컴포넌트 테스트: Vitest + Testing Library — **도입됨** (2026-08-21, `pnpm test`)
- 서버 상태: TanStack Query
- 폼 검증: React Hook Form + Zod
- OpenAPI 타입: 계약 동결 후 codegen
- E2E: 저장소 루트 `e2e/`의 Playwright 또는 기존 QA 합의 도구

### 테스트

```bash
pnpm test         # 1회 실행 (CI 와 같은 명령)
pnpm test:watch   # 감시 모드
```

⚠️ **여기 테스트가 잡는 것은 `lint` / `typecheck` / `build` 가 못 잡는 부류입니다.** 타입도
문법도 맞는데 순서만 틀린 상태 전환이라, 컴포넌트를 마운트하고 응답 도착 순서를 손으로
조작해야 재현됩니다. 첫 항목이 `AuthProvider` 의 경합 두 방향인 이유가 그것입니다 (#113).

## 실행

Node.js 22와 pnpm이 필요합니다.

```bash
cd apps/frontend
pnpm install
cp .env.example .env.local
pnpm dev
```

기본 주소는 `http://localhost:5173`입니다.

```bash
pnpm lint
pnpm typecheck
pnpm build
```

## Figma 기능을 서비스에 연결하는 방법

참고 시안의 정보 구조는 유지하되, 화면 문구와 데이터는 광고 생성 계약에 맞게 바꿉니다.

| Figma 영역 | 행복한 3팀 기능 | 구현 위치/계획 |
| --- | --- | --- |
| 시작·로그인 | 아이디/비밀번호 로그인 | `/login`, `POST /v1/auth/login` |
| 회원가입 | 가입 안내 | 계약상 현재 `501`; UI보다 계약 구현 여부를 먼저 확정 |
| 비밀번호 찾기 | 재설정 안내 | 공개 계약에 없음; 화면을 만들기 전에 OpenAPI 변경 필요 |
| 채팅 사이드바 | 새 세션, 세션 검색, 최근 세션 | `AppSidebar`, `GET /v1/sessions` |
| 입력 패널 | 사진, 제품명, 소구점, 메모, 화풍 | `BriefForm`, `POST /v1/sessions` |
| 기획안 패널 | 자동 채운 브리프 확인 | `Session.brief`, `Session.briefMeta` |
| 수정 버튼 | 브리프/시안 부분 교체 | `PATCH .../brief`, `PATCH .../draft` |
| 생성 버튼 | 텍스트 시안 생성 | `POST .../draft` |
| 대기 화면 | 최종 이미지 렌더 잡 | `POST .../finalize`, `GET /v1/jobs/{jobId}` |
| 성공·실패 | 결과/재시도 안내 | `Job.status`, `Job.result`, `Job.error` |
| 저장 | 만료 전 결과 이미지 다운로드 | `JobResult.imageUrl`, `expiresAt` 표시 |
| 설정·프로필 | 로그인 아이디, 로컬 환경설정 | `/settings`, `/profile`, `GET/PATCH /v1/me` |

## 화면과 라우트 계획

> **배포에서는 nginx가 vite 개발 서버의 두 가지 일을 이어받습니다** (`Dockerfile`, `nginx.conf`).
>
> | 개발 (vite) | 배포 (nginx) | 없으면 |
> | --- | --- | --- |
> | `/v1` 프록시 | `/v1` -> `backend:8000` | 다른 출처가 되어 `Secure` + `SameSite=Lax` 쿠키가 실리지 않고 **모든 요청이 401** |
> | SPA 폴백 | `try_files ... /index.html` | `BrowserRouter`라 `/login`을 주소창에 직접 치거나 새로고침하면 **404** |
>
> ⚠️ **HTTPS 종단이 아직 없습니다** (API_계약.md 8.3절). 세션 쿠키가 `Secure`라 브라우저는
> 평문 HTTP 응답에서 그 쿠키를 저장하지 않습니다. 즉 `http://<VM 주소>/`로는 **화면은 떠도
> 로그인이 성립하지 않습니다.** `http://localhost`는 예외라 로컬 스택에서는 됩니다.
> 종단 방식은 05 소관입니다.

| 경로 | 화면 | 보호 여부 | 상태 |
| --- | --- | --- | --- |
| `/login` | 로그인 | 공개 | **있음** |
| `/` | 새 광고 세션 생성 | 로그인 필요 | **있음** |
| `/sessions/:sessionId` | 브리프 확인 → 시안 → 확정 → 렌더 상태 → 결과 | 로그인 필요 | **있음** (시안 수정은 미연결) |
| `/settings` | 알림·표시 방식 등 기기 로컬 설정 | 로그인 필요 | 없음 |
| `/profile` | `loginId` 확인/수정, 비밀번호 변경 | 로그인 필요 | 없음 |

**화면이 없는 경로는 라우터에도 넣지 않았습니다.** 빈 경로를 미리 만들면 링크가 먼저 생기고
사용자는 아무것도 없는 화면에 도착합니다.

회원가입, 비밀번호 찾기 화면은 Figma에 있지만 현재 공개 API 계약과 동작 범위가 다릅니다. 경로부터
만들지 말고 `openapi.yaml`에 요청·응답·오류가 먼저 합의된 뒤 추가합니다.

## 백엔드 계약 매핑

프론트엔드는 `apps/backend`만 호출합니다. `apps/ai-engine`을 브라우저에서 직접 호출하지 않습니다.

| 순서 | 요청 | 중요한 화면 규칙 |
| --- | --- | --- |
| 1 | `POST /v1/sessions` | 이미지와 제품 정보를 multipart 한 번에 전송 |
| 2 | `PATCH /v1/sessions/{id}/brief` | 바꾼 필드만 `patch`에 포함하고 `revision` 전송 |
| 3 | `POST /v1/sessions/{id}/draft` | 실행 직전 브리프가 잠긴다는 사실을 확인받음 |
| 4 | `PATCH /v1/sessions/{id}/draft` | 만화는 컷별 scene/dialogue, 단일 광고는 copy/visualPlan만 수정 |
| 5 | `POST /v1/sessions/{id}/finalize` | 렌더 잡 ID를 받고 비동기 화면으로 전환 |
| 6 | `GET /v1/jobs/{jobId}` | `Retry-After` 헤더를 따라 폴링; 간격 하드코딩 금지 |

### 계약에서 특히 놓치기 쉬운 규칙

- 출력 유형은 `comic` 또는 `single_ad`이며 세션 생성 후 바꿀 수 없습니다.
- 만화는 정확히 6컷입니다. 컷 수 선택 UI를 제공하지 않습니다.
- 만화에는 `aspectRatio`가 없고 단일 광고에는 `character`가 없습니다.
- `adPlan`과 만화 컷의 `role`은 읽기 전용입니다.
- `messageMode: degraded`는 정상적인 열화 상태이며 오류 화면으로 보내지 않습니다.
- `needsInput`이 있으면 서버가 요구한 필드를 사용자에게 다시 묻습니다.
- 세션 `failed`는 복구하지 않고 새 세션을 시작합니다.
- 잡 실패도 상태 조회 HTTP 응답은 200이며, `Job.error.code`로 분기합니다.
- 결과 이미지 URL은 7일 후 만료되므로 `expiresAt`을 화면에 표시합니다.
- 409 `REVISION_CONFLICT`가 오면 최신 세션을 다시 조회한 뒤 사용자의 변경을 재적용할지 묻습니다.

## 상태 흐름

```mermaid
stateDiagram-v2
    [*] --> created
    created --> brief_filling
    brief_filling --> brief_ready: 정보 충족
    brief_filling --> failed: 재입력 후에도 부족
    brief_ready --> draft_generating: 시안 생성
    draft_generating --> draft_ready: 시안 성공
    draft_generating --> brief_ready: 시안 실패, 잠금 해제
    draft_ready --> finalized: 최종 확정
    finalized --> rendering: 잡 실행
    rendering --> completed: 결과 생성
    rendering --> failed: 잡 실패
```

세션 상태와 잡 상태를 한 enum으로 합치지 않습니다.

- 세션: `created | brief_filling | brief_ready | draft_generating | draft_ready | finalized | rendering | completed | failed`
- 잡: `queued | running | done | failed`

## 권장 폴더 구조

```text
apps/frontend/
  src/
    features/
      auth/             # 로그인, 세션 확인, 보호 라우트
        AuthProvider.test.tsx   # 상태 전환 회귀 테스트 (#113)
      studio/
        components/       # 사이드바, 브리프 폼, 브리프·시안·결과 패널
        api.ts            # 세션 · 잡 · 카탈로그 호출
        errors.ts         # 오류 코드 -> 화면 문구, 401 처리
        labels.ts         # 계약 enum -> 화면 문구
        useRenderJob.ts   # Retry-After 를 따르는 잡 폴링
        types.ts          # 계약과 맞춘 화면 타입
        NewSessionPage.tsx
        SessionPage.tsx
    shared/
      api/
        client.ts         # backend 호출 공통 경계
    test/
      setup.ts            # jest-dom 매처 등록 + 렌더 정리
    App.tsx
    main.tsx
    styles.css
  .env.example
  index.html
  package.json
  tsconfig.json
  vite.config.ts
```

기능이 커지면 `features/auth`, `features/session`, `features/render-job`으로 분리합니다. HTTP 요청은
컴포넌트 안에서 직접 호출하지 않고 `shared/api` 또는 각 feature의 API 모듈을 통과시킵니다.

## 구현 순서

> **1 ~ 4는 2026-08-19에 연결되었습니다.** 그 안에서 아직 안 된 항목만 아래에 표시해 둡니다.
> 템플릿 목록(`GET /v1/templates`)은 부르지 않습니다 - 출력 유형 둘은 계약의 enum 으로 고정이고,
> 예시 이미지가 비어 있는 지금 이 호출이 화면에 더해 주는 것이 없습니다. 예시 이미지가 붙는
> F1(06 일정 08-22)에서 부릅니다.

### 1. 인증과 보호 라우트

- `/v1/auth/login`, `/v1/auth/logout`, `/v1/me` 연결
- 401을 전역 로그인 화면으로 연결
- 쿠키 기반 인증 여부와 CSRF 정책을 백엔드와 확인

### 2. 세션 생성과 목록

- 템플릿과 화풍 목록 조회
- 이미지 형식·10MB·짧은 변 512px 사전 검증
- multipart 세션 생성
- 최근 세션 목록과 선택 상태

### 3. 브리프 확인과 시안

- `briefMeta.visibility`로 표시 여부 결정
- `filledBy`를 이용해 자동 입력값 표시
- 정보 부족·열화 상태의 추가 입력 흐름 — **됨** (F5, 2026-08-21). 브리프 수정으로 진행합니다
- 브리프 잠금 전 확인 모달 — 모달 대신 버튼 위 경고 문구로 두었습니다
- 시안의 허용 필드만 인라인 수정 — **미완.** `PATCH .../draft` 미연결

### 4. 렌더와 결과

- finalize 후 `jobId`를 세션 저장소에 보관 — 화면은 보관하지 않습니다. `jobId`는 서버가 세션에
  들고 있고 `GET /v1/sessions/{id}`가 돌려주므로, 사본을 두면 어긋나는 경우만 새로 생깁니다
- 서버 `Retry-After`를 따르는 폴링
- queued/running/done/failed 화면
- 결과 만료 시각과 다운로드

### 5. 품질

- 키보드만으로 전체 흐름 사용 가능
- 생성 상태를 `aria-live`로 알림
- 모바일 사이드바를 드로어로 전환
- 입력, 상태 전환, 오류 매핑 단위 테스트 — **일부.** 인증 상태 전환 4건이 있고 입력과 오류 매핑은 남았습니다
- 로그인 → 세션 생성 → 시안 → 렌더 → 저장 E2E

## 환경 변수

```dotenv
VITE_API_BASE_URL=
```

**비워 두는 것이 기본값입니다.** 빈 값은 "같은 출처"를 뜻하고, 개발 서버가 `/v1`을 백엔드로
프록시합니다(`vite.config.ts`). 브라우저는 `:5173` 하나만 상대하므로 CORS가 아예 생기지 않고,
세션 쿠키(`HttpOnly; Secure; SameSite=Lax`)가 그대로 실립니다.

절대 URL을 넣으면 프록시를 우회해 교차 출처 요청이 됩니다. 백엔드에는 CORS 미들웨어가 없고
`credentials: "include"`라 와일드카드 출처도 쓸 수 없어 브라우저가 막습니다. 프론트를 백엔드와
다른 출처에 배포하게 되면 CORS 설정과 쿠키의 `SameSite=None` 전환이 함께 필요합니다 —
[API_계약.md](../../docs/기술문서/API_계약.md) 8.3절.

브라우저에 포함되는 `VITE_` 변수에는 비밀 키를 넣지 않습니다. 모델 API 키와 저장소 자격증명은
백엔드 또는 인프라 환경에만 둡니다.

## 완료 기준

- OpenAPI에서 생성한 타입 또는 동일성을 검증하는 타입을 사용합니다.
- 새로고침 후에도 `sessionId`와 `jobId`로 진행 중 작업을 복구합니다.
- 빈 화면, 정보 부족, 열화, 생성 중, 부분 수정 실패, 최종 실패, 만료 결과를 각각 처리합니다.
- 409 충돌과 401 만료 세션에 사용자가 취할 다음 행동을 제공합니다.
- 모바일과 데스크톱에서 핵심 흐름이 동작합니다.
- `pnpm lint`, `pnpm typecheck`, `pnpm build`가 CI에서 필수로 통과합니다.

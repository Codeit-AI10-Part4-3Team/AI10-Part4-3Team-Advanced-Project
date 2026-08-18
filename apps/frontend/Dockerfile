# 프론트엔드 단독 이미지 — 정적 번들 + 같은 출처 프록시.
# 빌드 컨텍스트는 이 디렉토리(apps/frontend)입니다. 다른 앱의 소스를 참조하지 마세요.
#   docker build -t adgen-frontend:dev apps/frontend
#
# ⚠️ **이 이미지는 정적 파일만 서빙하는 것이 아닙니다.** `/v1` 을 backend 로 넘기는 프록시가
#    함께 들어 있고, 그것이 없으면 로그인이 성립하지 않습니다 — 세션 쿠키가 `Secure` +
#    `SameSite=Lax` 라(ADR-0013) 다른 출처로 가는 요청에는 실리지 않습니다. 개발에서
#    vite 가 하던 일(vite.config.ts)을 배포에서 이어받는 것이 nginx 쪽 설정입니다.

FROM node:22-slim AS build

WORKDIR /app

# pnpm 은 이 저장소가 고른 패키지 매니저입니다 (package.json 의 packageManager).
# corepack 으로 그 버전을 그대로 씁니다 — 전역 설치는 lockfile 과 버전이 갈립니다.
RUN corepack enable

# 의존성 레이어를 소스와 분리해 캐시 적중률을 높인다.
COPY package.json pnpm-lock.yaml ./
# ⚠️ `--frozen-lockfile`. lockfile 을 갱신하며 설치하면 배포된 번들이 CI 가 검증한 것과
#    다른 의존성으로 만들어지고, 그 차이는 어디에도 기록되지 않습니다.
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build


FROM nginx:1.29-alpine

# 기본 사이트 설정을 통째로 대체합니다. 덧붙이면 기본 server 블록이 먼저 잡습니다.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

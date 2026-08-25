/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Same-origin in development: the browser only ever talks to :5173, so there is no
    // preflight and the backend needs no Access-Control headers. The session cookie
    // (HttpOnly + Secure + SameSite=Lax, ADR-0013) rides along untouched because the
    // request never leaves this origin.
    //
    // ⚠️ This only works while API_BASE_URL stays relative (src/shared/api/client.ts).
    // An absolute URL such as http://localhost:8000 bypasses the proxy and lands straight
    // back on the CORS wall this exists to remove.
    proxy: {
      "/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // 화풍 예시 이미지. backend 가 볼륨에서 정적으로 내줍니다 (apps/backend/src/api/main.py).
      //
      // ⚠️ Without this the dev server answers **index.html with status 200** for an <img>,
      // so the picture is simply blank and nothing in the network tab says why. The
      // deployment has the same trap in the other direction — there it is nginx's SPA
      // fallback that catches it (apps/frontend/nginx.conf).
      //
      // ⚠️ Unlike /v1 this path is not in the contract, so no rule pulls it along: it is a
      // static asset served by us, and the two files above are the only places that know it
      // exists. Change one and change the other.
      //
      // The files are not committed (구현_범위 4.3절 keeps generated images out of the
      // repository), so locally the directory is usually empty and the URL 404s. That is the
      // same state the screen already handles for an empty `exampleImageUrl`.
      "/static/art-styles": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  // ⚠️ 테스트는 **브라우저 환경을 흉내 낸 곳**에서 돕니다 (`jsdom`). 여기서 잡으려는 것이
  // 순수 함수가 아니라 컴포넌트를 마운트한 뒤의 상태 전환이기 때문입니다 - `AuthProvider` 의
  // 세대 번호는 효과가 실제로 돌아야 재현됩니다.
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // `src` 밖에 테스트를 두지 않습니다. 검사 대상 옆에 있어야 같이 움직입니다.
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    // ⚠️ **CI 는 커버리지를 재지 않습니다.** `pnpm test:coverage` 로 사람이 볼 때만 씁니다 -
    // Sonar 에 프론트 lcov 를 물리려면 `sonarqube.yml` 과 `sonar-project.properties` 를 함께
    // 고쳐야 하고, 그것은 이 PR 범위 밖입니다. 문턱을 세우지 않은 것도 같은 이유입니다:
    // 지금 숫자는 인증 한 곳만 덮은 값이라 문턱으로 쓰면 나머지가 덮인 것처럼 보입니다.
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx"],
    },
  },
});

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
  },
});

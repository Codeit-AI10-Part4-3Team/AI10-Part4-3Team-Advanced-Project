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
});

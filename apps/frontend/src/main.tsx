import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./features/auth/AuthProvider";
import { LoginPage } from "./features/auth/LoginPage";
import { RequireAuth } from "./features/auth/RequireAuth";
import { NewSessionPage } from "./features/studio/NewSessionPage";
import { SessionPage } from "./features/studio/SessionPage";
import { NotFoundPage } from "./shared/NotFoundPage";
import "./styles.css";

// 경로 계획의 정본은 apps/frontend/README.md 입니다. 여기에는 그중 지금 존재하는 것만
// 있습니다 - `/settings` 와 `/profile` 은 화면이 없으므로 경로도 두지 않습니다. 빈 경로를
// 미리 만들면 링크가 먼저 생기고 사용자는 아무것도 없는 화면에 도착합니다.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <App />
              </RequireAuth>
            }
          >
            <Route path="/" element={<NewSessionPage />} />
            <Route path="/sessions/:sessionId" element={<SessionPage />} />
          </Route>
          {/* ⚠️ **리다이렉트가 아니라 화면입니다.** `Navigate to="/"` 로 두면 이 규칙이
              `RequireAuth` 보다 먼저 돌아 되돌아갈 주소가 언제나 `/` 가 되고, 로그인 복귀
              경로 전체가 도달 불가능해집니다 (#114). */}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./features/auth/AuthProvider";
import { LoginPage } from "./features/auth/LoginPage";
import { RequireAuth } from "./features/auth/RequireAuth";
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
            path="/"
            element={
              <RequireAuth>
                <App />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);

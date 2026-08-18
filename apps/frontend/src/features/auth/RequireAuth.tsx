import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./useAuth";

/**
 * 로그인이 필요한 화면을 감쌉니다.
 *
 * ⚠️ **이것은 편의이지 방어선이 아닙니다.** 접근 제어는 서버가 합니다 - 미인증은 401, 남의
 * 세션은 404 (INV-9). 여기서 하는 일은 어차피 401 로 끝날 요청을 보내지 않고 로그인 화면을
 * 먼저 보여 주는 것뿐이며, 이 컴포넌트를 우회한다고 남의 데이터가 보이지는 않습니다.
 *
 * ⚠️ `status === "checking"` 동안 로그인 화면으로 보내지 않습니다. 첫 렌더에서 `GET /v1/me`
 * 가 아직 돌아오지 않았을 뿐이고, 그때 넘겨 버리면 **새로고침할 때마다 로그인 화면이 한 번씩
 * 깜빡입니다.**
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "checking") {
    return (
      <main className="auth-shell">
        <p className="auth-lead">세션을 확인하고 있습니다...</p>
      </main>
    );
  }

  if (status === "signed_out") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}

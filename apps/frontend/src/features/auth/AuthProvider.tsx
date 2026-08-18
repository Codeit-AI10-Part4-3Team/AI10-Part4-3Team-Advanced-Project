import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "../../shared/api/client";
import { AuthContext, type AuthStatus } from "./AuthContext";
import { fetchMe, login, logout } from "./api";
import type { Me } from "./types";

/**
 * 로그인 상태의 단일 출처.
 *
 * ⚠️ **브라우저는 세션 쿠키를 읽을 수 없습니다.** `HttpOnly` 이기 때문이고(ADR-0013), 그래서
 * "로그인했는가"의 답은 화면이 들고 있는 값이 아니라 `GET /v1/me` 의 응답입니다. 첫 렌더에서
 * 한 번 물어보는 이유가 이것입니다 - 새로고침 후에도, 다른 탭에서 로그아웃한 뒤에도 서버가
 * 답을 갖고 있고 우리는 갖고 있지 않습니다.
 *
 * ⚠️ 토큰 수명은 24시간이고 갱신 경로가 없습니다(세션_보관_정책 1.4절). 만료는 다음 요청의
 * 401 로 나타나며, 여기서 미리 세어 두지 않습니다 - 시계가 어긋나면 서버가 아직 받아 주는
 * 세션을 화면이 먼저 끊습니다.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchMe()
      .then((current) => {
        if (cancelled) return;
        setMe(current);
        setStatus("signed_in");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // 401 은 "로그인하지 않았다"이지 장애가 아닙니다. 그 밖의 실패(백엔드가 죽었거나
        // 프록시가 없는 경우)도 여기서는 같은 답으로 둡니다 - 어느 쪽이든 화면이 할 수
        // 있는 일은 로그인 화면을 보여 주는 것뿐이고, 로그인 시도가 진짜 원인을 말해 줍니다.
        if (!(error instanceof ApiError)) {
          console.warn("세션 확인에 실패했습니다.", error);
        }
        setMe(null);
        setStatus("signed_out");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (loginId: string, password: string) => {
    const current = await login(loginId, password);
    setMe(current);
    setStatus("signed_in");
  }, []);

  const signOut = useCallback(async () => {
    try {
      await logout();
    } catch (error: unknown) {
      // ⚠️ 삼키는 것이 아니라 **여기서 끝내는 것**입니다. 아래 `finally` 가 이미 화면을
      // 로그아웃 상태로 만들었으므로 이 실패에 사용자가 할 일은 없는데, 다시 던지면 호출부
      // (`void signOut()`, AppSidebar) 가 받지 않아 unhandled rejection 으로 남습니다 -
      // 처리를 마친 실패가 콘솔에는 처리되지 않은 오류로 보고됩니다.
      //
      // 401 은 토큰이 이미 만료된 경우이고 계약이 그렇게 답하도록 되어 있습니다
      // (`POST /v1/auth/logout` 은 유효한 세션을 요구합니다). `finally` 주석이 말하는 바로
      // 그 상황이라 조용히 넘어갑니다. 그 밖의 실패(백엔드 다운, 프록시 없음)는 서버에
      // 세션이 남아 있을 수 있어 흔적을 남깁니다 - 화면만 로그아웃된 상태이기 때문입니다.
      if (!(error instanceof ApiError && error.status === 401)) {
        console.warn("로그아웃 요청이 실패했습니다. 화면에서는 로그아웃합니다.", error);
      }
    } finally {
      // ⚠️ `finally`. 로그아웃 요청이 실패해도 화면에서는 내보냅니다 - 이미 만료된 토큰이면
      // 401 이 돌아오는데, 그때 로그인 상태로 붙들어 두면 사용자는 아무것도 할 수 없는
      // 화면에 갇힙니다.
      setMe(null);
      setStatus("signed_out");
    }
  }, []);

  const value = useMemo(() => ({ status, me, signIn, signOut }), [status, me, signIn, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

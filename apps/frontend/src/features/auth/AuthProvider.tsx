import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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

  // ⚠️ 세대 번호. 늦게 도착한 응답이 그 사이 확정된 상태를 덮어쓰는 것을 막습니다.
  //
  // 마운트 시점의 `fetchMe` 가 도는 동안 사용자가 로그인을 끝낼 수 있습니다. 그때 뒤늦게
  // 도착한 401 이 `signed_out` 을 쓰면, 로그인에 성공한 사용자가 아무 설명 없이 로그인
  // 화면으로 되돌아옵니다. 다시 치면 들어가지므로 사용자는 자기 오타로 여기고 버그로
  // 신고되지 않습니다.
  //
  // 규칙은 하나입니다. **상태를 확정하는 쪽(`signIn`/`signOut`/언마운트)이 번호를 올리고,
  // 비동기 응답은 출발할 때의 번호와 다르면 아무것도 하지 않습니다.** 언마운트만 막는
  // 플래그로는 부족한 이유가 이것입니다 - 컴포넌트는 살아 있는데 상태만 갈아치워집니다.
  const epochRef = useRef(0);

  useEffect(() => {
    const epoch = epochRef.current;

    fetchMe()
      .then((current) => {
        if (epochRef.current !== epoch) return;
        setMe(current);
        setStatus("signed_in");
      })
      .catch((error: unknown) => {
        if (epochRef.current !== epoch) return;
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
      epochRef.current += 1;
    };
  }, []);

  const signIn = useCallback(async (loginId: string, password: string) => {
    const current = await login(loginId, password);
    // 진행 중인 세션 확인의 결과를 버립니다 - 이 시점부터는 로그인 응답이 더 최신입니다.
    epochRef.current += 1;
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
      //
      // 여기서도 세대 번호를 올립니다. 로그아웃 직전에 출발한 `fetchMe` 가 200 으로 돌아와
      // `signed_in` 을 되살리면, 사용자는 로그아웃 버튼을 눌렀는데 로그인 상태로 남습니다.
      epochRef.current += 1;
      setMe(null);
      setStatus("signed_out");
    }
  }, []);

  const value = useMemo(() => ({ status, me, signIn, signOut }), [status, me, signIn, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

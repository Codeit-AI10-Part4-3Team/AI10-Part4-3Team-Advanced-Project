import { createContext } from "react";
import type { Me } from "./types";

export type AuthStatus = "checking" | "signed_in" | "signed_out";

export interface AuthValue {
  status: AuthStatus;
  me: Me | null;
  /** 실패하면 던집니다. 로그인 화면이 그 오류를 문구로 바꿔야 하기 때문입니다. */
  signIn: (loginId: string, password: string) => Promise<void>;
  /**
   * ⚠️ **던지지 않습니다.** `signIn` 과 다른 점이고 의도된 비대칭입니다 - 로그아웃은 요청이
   * 실패해도 화면에서는 성립하므로(`AuthProvider`) 호출부에 넘길 결정이 남지 않습니다.
   * 이것이 `void signOut()` 로 불러도 되는 근거입니다. 던지게 바꾸면 그 호출부가 조용히
   * unhandled rejection 이 됩니다.
   */
  signOut: () => Promise<void>;
}

// ⚠️ 컨텍스트와 프로바이더를 다른 파일에 둡니다. 한 파일에 컴포넌트와 컴포넌트가 아닌 것을
// 함께 내보내면 react-refresh 규칙(eslint)이 걸리고, 실제로도 편집할 때마다 화면 상태가
// 통째로 날아갑니다.
export const AuthContext = createContext<AuthValue | null>(null);

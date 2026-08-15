import { createContext } from "react";
import type { Me } from "./types";

export type AuthStatus = "checking" | "signed_in" | "signed_out";

export interface AuthValue {
  status: AuthStatus;
  me: Me | null;
  signIn: (loginId: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

// ⚠️ 컨텍스트와 프로바이더를 다른 파일에 둡니다. 한 파일에 컴포넌트와 컴포넌트가 아닌 것을
// 함께 내보내면 react-refresh 규칙(eslint)이 걸리고, 실제로도 편집할 때마다 화면 상태가
// 통째로 날아갑니다.
export const AuthContext = createContext<AuthValue | null>(null);

import { useContext } from "react";
import { AuthContext, type AuthValue } from "./AuthContext";

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth 는 AuthProvider 안에서만 쓸 수 있습니다.");
  }
  return value;
}

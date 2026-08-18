import { apiRequest, apiRequestNoContent } from "../../shared/api/client";
import type { Me } from "./types";

// ⚠️ No token is read, stored or attached anywhere in this file, and that is the design.
// The session cookie is HttpOnly (ADR-0013), so script cannot see it and `credentials:
// "include"` in the client is what carries it. Anything here that touched localStorage
// would be undoing the reason the cookie is HttpOnly in the first place.

export function login(loginId: string, password: string): Promise<Me> {
  return apiRequest<Me>("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loginId, password }),
  });
}

export function logout(): Promise<void> {
  // 204, so there is no body to parse — see `apiRequestNoContent`.
  return apiRequestNoContent("/v1/auth/logout", { method: "POST" });
}

export function fetchMe(): Promise<Me> {
  return apiRequest<Me>("/v1/me");
}

// Relative by default, so requests stay on the page's own origin and the Vite dev proxy
// forwards them to the backend (vite.config.ts). Pointing this at an absolute URL opts
// into cross-origin requests, which the backend cannot serve: it registers no CORS
// middleware, and `credentials: "include"` below rules out a wildcard origin anyway.
// Deploying the frontend on a different origin needs CORS *and* SameSite=None on the
// session cookie — docs/기술문서/API_계약.md 8.3절.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    ...init,
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { code?: string; message?: string }
      | null;
    throw new ApiError(
      response.status,
      body?.code ?? "INTERNAL",
      body?.message ?? "요청을 처리하지 못했습니다.",
    );
  }

  return response.json() as Promise<T>;
}

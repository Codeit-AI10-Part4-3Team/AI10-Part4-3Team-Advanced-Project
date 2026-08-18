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

async function send(path: string, init?: RequestInit): Promise<Response> {
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

  return response;
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init);
  return response.json() as Promise<T>;
}

// ⚠️ 204 는 본문이 없으므로 `response.json()` 이 파싱 오류로 던집니다. 로그아웃이 실제로
// 성공했는데 화면에는 실패로 보이는 상태가 되고, 사용자는 이미 만료된 쿠키를 들고 다시
// 시도하게 됩니다. 계약에서 204 를 쓰는 경로(`POST /v1/auth/logout`)는 이쪽으로 부릅니다.
export async function apiRequestNoContent(path: string, init?: RequestInit): Promise<void> {
  await send(path, init);
}

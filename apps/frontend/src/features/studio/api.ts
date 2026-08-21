import { apiRequest, apiRequestWithHeaders } from "../../shared/api/client";
import type {
  ArtStyle,
  BriefPatch,
  FinalizeAccepted,
  Job,
  Session,
  SessionCreateInput,
  SessionSummary,
} from "./types";

// 계약: packages/contracts/openapi.yaml 의 `sessions` · `jobs` · `catalog` 태그.
//
// 프론트가 부르는 것은 `apps/backend` 뿐입니다. `apps/ai-engine` 은 브라우저에서 직접 부르지
// 않습니다 - 그쪽 경로(`/v1/draft:generate` 등)는 내부 계약이고 인증이 걸려 있지 않습니다.

export function listSessions(): Promise<SessionSummary[]> {
  return apiRequest<SessionSummary[]>("/v1/sessions");
}

export function getSession(sessionId: string): Promise<Session> {
  return apiRequest<Session>(`/v1/sessions/${encodeURIComponent(sessionId)}`);
}

export function listArtStyles(): Promise<ArtStyle[]> {
  return apiRequest<ArtStyle[]>("/v1/art-styles");
}

/**
 * 사진과 제품 정보를 **한 번에** 보냅니다. 업로드를 별도 경로로 나누지 않은 이유는 왕복이
 * 둘로 늘고 "어느 세션에도 속하지 않은 이미지"라는 상태가 새로 생기기 때문입니다
 * (API_계약.md 8.1절).
 *
 * ⚠️ 201 이 "브리프가 다 채워졌다"는 뜻이 아닙니다. 세 갈래가 같은 상태 코드를 씁니다 -
 * 정상(`brief_ready`), 정보 부족(`brief_filling` + `needsInput`), 의존 장애로 인한 열화
 * (`brief_filling` + `messageMode: degraded`). 뒤의 둘은 오류가 아니므로 오류 화면으로
 * 보내지 않습니다.
 */
export function createSession(input: SessionCreateInput): Promise<Session> {
  const form = new FormData();
  form.append("outputType", input.outputType);
  form.append("productImage", input.productImage);
  form.append("productName", input.productName);
  form.append("sellingPoint", input.sellingPoint);
  // 선택 항목은 비었으면 아예 싣지 않습니다. 빈 문자열을 보내도 서버가 같게 처리하지만,
  // 그때 "미선택"과 "빈 값을 골랐음"이 전선에서 구분되지 않습니다.
  if (input.note) form.append("note", input.note);
  if (input.artStyle) form.append("artStyle", input.artStyle);

  // ⚠️ `Content-Type` 을 직접 넣지 마세요. `FormData` 를 넘기면 브라우저가 multipart 경계
  // 문자열까지 포함해 헤더를 만듭니다. 손으로 `multipart/form-data` 를 넣으면 경계가 빠져
  // 서버가 본문을 파싱하지 못하고, 증상은 422 라 입력값 문제처럼 보입니다.
  return apiRequest<Session>("/v1/sessions", { method: "POST", body: form });
}

/**
 * 브리프 부분 교체. **바꾼 키만 보냅니다** - 전체 문서를 되돌려 보내면 원문을 지키는 쪽이
 * 서버가 아니라 화면이 되고, 화면의 버그가 브리프를 조용히 덮어씁니다 (API_계약 PATCH 절).
 *
 * `revision` 은 낙관적 잠금입니다. 값이 뒤처졌으면 409 `REVISION_CONFLICT` 이고, 그때 화면이
 * 할 일은 다시 읽는 것입니다 - `ETag` 왕복을 두지 않은 이유는 계약에 적혀 있습니다.
 *
 * ⚠️ **시안이 생긴 뒤에는 409 `STATE_CONFLICT` 입니다** (INV-7). 시안이 브리프에서 나온
 * 산출물이라 근거가 나중에 바뀌면 시안이 무엇에 근거했는지 알 수 없게 됩니다. 그래서 화면은
 * 잠긴 뒤에 고치기 버튼을 내려야 하며, 이 호출로 확인시키는 것은 안내가 아니라 오류입니다.
 *
 * ⚠️ 빈 patch 는 422 입니다 (`minProperties: 1`). 바뀐 값이 없으면 **부르지 마세요**.
 *
 * `needsInput` 이나 `degraded` 세션에서 `note` 를 채우면 서버가 추론을 다시 시도하므로,
 * 응답의 `state` 와 `messageMode` 가 요청 전과 달라질 수 있습니다.
 */
export function patchBrief(
  sessionId: string,
  revision: number,
  patch: BriefPatch,
): Promise<Session> {
  return apiRequest<Session>(`/v1/sessions/${encodeURIComponent(sessionId)}/brief`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ revision, patch }),
  });
}

/**
 * 시안 생성. **이 요청이 브리프를 잠급니다** (INV-7).
 *
 * 동기입니다. 텍스트 생성이라 폴링 경로를 하나 더 둘 만한 길이가 아니며, 상한 60초를 넘기면
 * 504 `GENERATION_TIMEOUT` 입니다. 실패하면 세션은 `brief_ready` 로 되돌아가고 잠금도
 * 풀립니다 (ADR-0012).
 */
export function generateDraft(sessionId: string): Promise<Session> {
  return apiRequest<Session>(`/v1/sessions/${encodeURIComponent(sessionId)}/draft`, {
    method: "POST",
  });
}

/** 확정 + 렌더 잡 접수. 동기와 비동기가 갈리는 유일한 지점이고, 세션당 1회입니다 (INV-3). */
export function finalizeSession(sessionId: string): Promise<FinalizeAccepted> {
  return apiRequest<FinalizeAccepted>(`/v1/sessions/${encodeURIComponent(sessionId)}/finalize`, {
    method: "POST",
  });
}

/**
 * 잡 조회. **렌더가 실패해도 200 입니다** - 조회는 성공했고 잡이 실패한 것이라, HTTP 오류로
 * 만들면 "서버에 못 닿았다"와 "그림을 못 만들었다"를 화면이 구분하지 못합니다.
 *
 * `Retry-After` 는 `queued` · `running` 일 때만 실립니다. 끝난 잡에는 다음 조회가 없으므로
 * 값이 없는 것이 정상이고, 그때 `retryAfterS` 는 `undefined` 입니다.
 */
export async function getJob(jobId: string): Promise<{ job: Job; retryAfterS?: number }> {
  const { data, headers } = await apiRequestWithHeaders<Job>(
    `/v1/jobs/${encodeURIComponent(jobId)}`,
  );
  const header = headers.get("Retry-After");
  const seconds = header === null ? Number.NaN : Number(header);
  return {
    job: data,
    retryAfterS: Number.isFinite(seconds) && seconds > 0 ? seconds : undefined,
  };
}

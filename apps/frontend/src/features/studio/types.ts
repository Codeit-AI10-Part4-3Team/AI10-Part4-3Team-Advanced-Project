// 계약: packages/contracts/openapi.yaml. 필드는 camelCase 이고, 이 파일은 그 스키마를 손으로
// 옮긴 것입니다 (codegen 은 계약 동결 이후 - README "기술 선택").
//
// ⚠️ **`null` 은 계약 전체에서 금지입니다.** "아직 없음"은 값이 아니라 **키의 부재**로
// 표현하므로 선택 필드는 `?:` 이고, 화면은 값을 비교하지 않고 키가 있는지로 분기합니다
// (`Session.draft`, `Session.jobId`, `Job.result`, `Job.error`). 여기에 `| null` 을 하나라도
// 섞으면 그 순간 두 가지 "없음"이 생기고, 분기 규칙이 필드마다 달라집니다.

export type OutputType = "comic" | "single_ad";

export type SessionState =
  | "created"
  | "brief_filling"
  | "brief_ready"
  | "draft_generating"
  | "draft_ready"
  | "finalized"
  | "rendering"
  | "completed"
  | "failed";

export type JobStatus = "queued" | "running" | "done" | "failed";

export type MessageMode = "normal" | "degraded";

export type ErrorCode =
  | "INVALID_REQUEST"
  | "NOT_FOUND"
  | "UNAUTHORIZED"
  | "INVALID_CREDENTIALS"
  | "DUPLICATE_ACCOUNT"
  | "NOT_IMPLEMENTED"
  | "RATE_LIMITED"
  | "UPSTREAM_UNAVAILABLE"
  | "INTERNAL"
  | "INSUFFICIENT_INPUT"
  | "INVALID_IMAGE"
  | "CONTENT_POLICY_REJECTED"
  | "GENERATION_TIMEOUT"
  | "REVISION_CONFLICT"
  | "STATE_CONFLICT";

export interface ArtStyle {
  artStyleId: string;
  name: string;
  exampleImageUrl: string;
}

export interface Character {
  appearance: string;
  outfit: string;
}

export interface Brief {
  /**
   * 앱 상대 경로(`/v1/sessions/{id}/image`)이고 호스트가 붙지 않습니다.
   *
   * ⚠️ **사진이 만료되면 빈 문자열입니다.** 세션은 7일, 사진은 24시간이라 세션은 있는데
   * 사진만 없는 구간이 생깁니다. 화면은 이 값이 비었는지로 분기하고, 비어 있으면 `<img>` 를
   * 아예 그리지 않습니다 - 그리고 나서 404 를 받으면 깨진 이미지가 남습니다.
   */
  productImageUrl: string;
  productName: string;
  sellingPoint: string;
  note: string;
  category: string;
  target: string;
  artStyle: string;
  /** 만화형만. 단일 광고형에는 키 자체가 없습니다. */
  character?: Character;
  /** 단일 광고형만. 만화형에는 키 자체가 없습니다. */
  aspectRatio?: string;
}

export type FilledBy = "user" | "inferred" | "random" | "default" | "fixed" | "system";

export interface FieldMeta {
  filledBy: FilledBy;
  visibility: "hidden" | "editable";
}

/** `brief` 와 같은 키를 가집니다. `hidden` 필드는 양쪽에서 함께 빠집니다. */
export interface BriefMeta {
  productImageUrl: FieldMeta;
  productName: FieldMeta;
  sellingPoint: FieldMeta;
  note: FieldMeta;
  category: FieldMeta;
  target: FieldMeta;
  artStyle: FieldMeta;
  character?: FieldMeta;
  aspectRatio?: FieldMeta;
}

export interface NeedsInput {
  field: string;
  reason: string;
}

export type PanelRole = "hook" | "setup" | "problem" | "solution" | "proof" | "cta";

export interface Panel {
  index: number;
  role: PanelRole;
  scene: string;
  dialogue: string;
}

export interface ComicDraft {
  adPlan: string;
  /** 정확히 6개입니다. 0개도 7개도 유효하지 않습니다 (INV-1). */
  panels: Panel[];
}

export interface SingleAdDraft {
  adPlan: string;
  copy: string;
  visualPlan: string;
}

export type Draft = ComicDraft | SingleAdDraft;

export function isComicDraft(draft: Draft): draft is ComicDraft {
  return "panels" in draft;
}

export interface Session {
  sessionId: string;
  state: SessionState;
  outputType: OutputType;
  /** 부분 교체마다 1 증가합니다. `PATCH` 요청의 본문에 실어 낙관적 잠금을 겁니다. */
  revision: number;
  messageMode: MessageMode;
  brief: Brief;
  briefMeta: BriefMeta;
  /** 시안 생성 전에는 키가 없습니다. */
  draft?: Draft;
  /** 추론이 돌았는데 판단이 서지 않은 경우에만 있습니다. 열화(degraded)와는 다릅니다. */
  needsInput?: NeedsInput;
  /** 확정 전에는 키가 없습니다. */
  jobId?: string;
  createdAt: string;
  updatedAt: string;
}

export interface SessionSummary {
  sessionId: string;
  state: SessionState;
  outputType: OutputType;
  productName: string;
  messageMode: MessageMode;
  createdAt: string;
  updatedAt: string;
}

export interface JobResult {
  /** 앱 상대 경로(`/v1/jobs/{jobId}/image`). `status: done` 일 때만 실립니다. */
  imageUrl: string;
  width: number;
  height: number;
  /** 결과 이미지의 보존 만료 시각(7일). 만료는 응답이 아니라 이 값으로 미리 압니다. */
  expiresAt: string;
}

export interface ApiErrorBody {
  code: ErrorCode;
  message: string;
}

export interface Job {
  jobId: string;
  status: JobStatus;
  /** 대기 중일 때만 있습니다. */
  queuePosition?: number;
  /** `done` 일 때만 있습니다. */
  result?: JobResult;
  /** `failed` 일 때만 있습니다. */
  error?: ApiErrorBody;
}

export interface FinalizeAccepted {
  jobId: string;
  statusUrl: string;
}

/**
 * 세션 생성 폼이 들고 있는 값입니다. 계약의 `SessionCreateRequest` 와 한 가지가 다릅니다 -
 * 올릴 때는 파일 자체(`productImage`)이고 읽을 때는 참조(`Brief.productImageUrl`)라,
 * 여기서만 `File` 을 들고 있습니다.
 */
export interface SessionCreateInput {
  outputType: OutputType;
  productImage: File;
  productName: string;
  sellingPoint: string;
  note: string;
  /** 빈 문자열은 "미선택"입니다. 그때 서버가 후보군에서 무작위로 채웁니다. */
  artStyle: string;
}

/**
 * 계약의 `BriefPatch`. **바꾸려는 키만 담습니다** - 키를 빼는 것이 "안 바꿈"이고, 값을 비우는
 * 것은 빈 문자열입니다. 키 생략으로는 비울 수 없습니다.
 *
 * ⚠️ **`productImageUrl` 이 없는 것은 빠뜨린 것이 아닙니다.** `briefMeta` 는 그 필드를
 * `editable` 로 표시하지만 계약의 `BriefPatch` 에는 자리가 없습니다 - 재업로드 경로를 정한
 * 적이 없기 때문입니다. 화면에서 사진 교체를 제공하기로 하면 계약이 multipart 를 함께 받도록
 * 먼저 고쳐야 하며, 그 전에 여기 필드를 늘리면 422 로 거절됩니다.
 *
 * ⚠️ `panelCount` 도 없습니다. `hidden` 이라 patch 대상이 아닙니다 (INV-4).
 */
export interface BriefPatch {
  productName?: string;
  sellingPoint?: string;
  note?: string;
  category?: string;
  target?: string;
  artStyle?: string;
  character?: Character;
  aspectRatio?: string;
}

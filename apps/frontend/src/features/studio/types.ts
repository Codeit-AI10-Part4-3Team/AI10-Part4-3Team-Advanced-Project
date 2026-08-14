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

export interface BriefInput {
  outputType: OutputType;
  productName: string;
  sellingPoint: string;
  note: string;
  artStyle: string;
  productImageName: string;
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

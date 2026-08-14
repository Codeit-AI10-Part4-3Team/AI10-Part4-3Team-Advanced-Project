import type { SessionSummary } from "./types";

export const mockSessions: SessionSummary[] = [
  {
    sessionId: "demo-session-1",
    state: "draft_ready",
    outputType: "single_ad",
    productName: "여름 블렌드 캠페인",
    messageMode: "normal",
    createdAt: "2026-08-14T00:00:00Z",
    updatedAt: "2026-08-14T01:30:00Z",
  },
  {
    sessionId: "demo-session-2",
    state: "brief_ready",
    outputType: "comic",
    productName: "카페 오픈 6컷 만화",
    messageMode: "normal",
    createdAt: "2026-08-13T00:00:00Z",
    updatedAt: "2026-08-13T08:10:00Z",
  },
];

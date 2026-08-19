import type { JobStatus, OutputType, PanelRole, SessionState } from "./types";

// 계약의 enum 을 화면 문구로 옮기는 표입니다. 값 자체(`single_ad`, `queued`)를 화면에 그대로
// 쓰지 않는 이유는, 그렇게 하면 계약의 식별자가 사용자 문구가 되어 이름을 못 바꾸게 되기
// 때문입니다.

export const OUTPUT_TYPE_LABEL: Record<OutputType, string> = {
  comic: "6컷 광고 만화",
  single_ad: "단일 광고",
};

export const SESSION_STATE_LABEL: Record<SessionState, string> = {
  created: "생성됨",
  brief_filling: "정보 확인 필요",
  brief_ready: "브리프 준비됨",
  draft_generating: "시안 생성 중",
  draft_ready: "시안 준비됨",
  finalized: "확정됨",
  rendering: "이미지 생성 중",
  completed: "완료",
  failed: "실패",
};

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: "대기 중",
  running: "생성 중",
  done: "완료",
  failed: "실패",
};

/** 기획서 7.3 의 6단계와 1:1 입니다. 순서는 `index` 가 정하며 사용자가 바꾸지 않습니다 (INV-5). */
export const PANEL_ROLE_LABEL: Record<PanelRole, string> = {
  hook: "후킹",
  setup: "상황 설정",
  problem: "문제 제시",
  solution: "해결 제시",
  proof: "근거 제시",
  cta: "행동 유도",
};

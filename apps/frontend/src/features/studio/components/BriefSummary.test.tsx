import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BriefSummary } from "./BriefSummary";
import type { Session, SessionState } from "../types";

/**
 * 브리프 요약이 쓰는 **화면 문구**를 고정합니다.
 *
 * ⚠️ **입력 화면과 같은 말을 써야 합니다.** 계약의 필드는 `sellingPoint` 이지만 화면 문구는
 * "제품 특징" 입니다 - "소구점" 이 업계 용어라 처음 쓰는 사람이 무엇을 적어야 할지 모릅니다.
 * 같은 값을 두 화면이 다른 이름으로 부르면 사용자는 **다른 것을 묻는다고 읽습니다.**
 *
 * ⚠️ 실제로 그렇게 어긋나 있었습니다 - 2026-08-26 에 `BriefForm` 만 고치고 여기를 빠뜨려
 * 입력은 "제품 장점"(그때의 문구), 요약은 "핵심 소구점" 이었습니다. 이 시험이 그 재발을
 * 막습니다. 라벨이 "제품 특징" 이 된 것은 2026-08-28 (PR #309) 입니다.
 */

function session(over: Partial<Session> = {}): Session {
  return {
    sessionId: "s1",
    revision: 1,
    state: "brief_ready" as SessionState,
    outputType: "single_ad",
    createdAt: "2026-08-28T00:00:00Z",
    brief: {
      productName: "행복 블렌드",
      sellingPoint: "핸드드립",
      category: "식품",
      target: "30대",
      artStyle: "",
      productImageUrl: "",
    },
    briefMeta: { sellingPoint: { visibility: "editable" } },
    ...over,
  } as Session;
}

function setup(editable = false, over: Partial<Session> = {}) {
  render(<BriefSummary session={session(over)} editable={editable} onSave={vi.fn()} />);
}

describe("제품 특징 문구", () => {
  it("읽기 화면이 입력 화면과 같은 말을 쓴다", () => {
    setup();
    expect(screen.getByText(/제품 특징/)).toBeInTheDocument();
    expect(screen.queryByText(/소구점/)).not.toBeInTheDocument();
  });

  it("고치기를 열어도 같은 말을 쓴다", () => {
    // 읽기와 편집이 다른 이름을 쓰면 고치기를 누른 순간 다른 항목처럼 보입니다.
    setup(true);
    fireEvent.click(screen.getByRole("button", { name: "고치기" }));
    expect(screen.getByLabelText(/제품 특징/)).toBeInTheDocument();
    expect(screen.queryByText(/소구점/)).not.toBeInTheDocument();
  });
});

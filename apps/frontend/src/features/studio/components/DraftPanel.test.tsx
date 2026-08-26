import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DraftPanel } from "./DraftPanel";
import type { Job, Session, SessionState } from "../types";

/**
 * 시안 패널의 상태별 표시.
 *
 * ⚠️ **여기서 고정하는 것은 "무엇이 오류가 아닌가" 입니다.** 정보 부족(`needsInput`)은 대화의
 * 한 단계이고(기획서 9.3) 열화(`messageMode: degraded`)는 설계된 동작입니다(ADR-0005).
 * 둘을 오류로 보내면 사용자는 자기가 뭘 잘못했다고 읽고, 팀은 설계된 열화를 장애로 보고합니다.
 *
 * ⚠️ **만화형 게이트도 여기서 고정합니다.** 이 패널이 만화형이면 시안 생성 버튼을 내리는데,
 * 그 조건이 사라지면 기본 설정(`stub`)으로 도는 사람이 실장애와 구분 안 되는 오류를 봅니다
 * (미결정_대장 N22, 이슈 #271). **N22 가 닫혀 게이트를 걷을 때 이 시험이 함께 바뀌어야
 * 한다는 것이 표시입니다** - 조용히 지워지면 안 됩니다.
 */

function session(over: Partial<Session> = {}): Session {
  return {
    sessionId: "s1",
    revision: 1,
    state: "brief_ready" as SessionState,
    outputType: "single_ad",
    createdAt: "2026-08-26T00:00:00Z",
    brief: {
      productName: "행복 블렌드",
      sellingPoint: "핸드드립",
      category: "식품",
      target: "30대",
      artStyle: "",
      productImageUrl: "",
    },
    briefMeta: {},
    ...over,
  } as Session;
}

function setup(over: Partial<Session> = {}, extra: Partial<Parameters<typeof DraftPanel>[0]> = {}) {
  const props = {
    session: session(over),
    job: null as Job | null,
    pollingStopped: false,
    pending: null as "draft" | "finalize" | null,
    onGenerate: vi.fn(),
    onFinalize: vi.fn(),
    onReload: vi.fn(),
    ...extra,
  };
  render(<DraftPanel {...props} />);
  return props;
}

const generateButton = () => screen.queryByRole("button", { name: /시안 만들기/ });
const finalizeButton = () => screen.queryByRole("button", { name: /확정하고 이미지 만들기/ });

describe("만화형 게이트", () => {
  it("만화형에는 시안 만들기 버튼이 없다", () => {
    // ⚠️ 스텁 분기가 만화형을 거절하므로(`ai_engine/draft.py`), 버튼을 두면 사용자가
    // "엔진에 연결하지 못했습니다" 를 봅니다 - 없는 장애를 있다고 말하는 화면입니다.
    setup({ outputType: "comic" });
    expect(generateButton()).not.toBeInTheDocument();
    expect(screen.getByText(/만화형은 아직 시안 생성이 열려 있지 않습니다/)).toBeInTheDocument();
  });

  it("단일 광고형에는 있다", () => {
    setup({ outputType: "single_ad" });
    expect(generateButton()).toBeInTheDocument();
  });

  it("게이트는 brief_ready 에서만 걸린다", () => {
    // 시안이 이미 있으면 안내가 아니라 시안을 보여 줘야 합니다.
    setup({ outputType: "comic", state: "draft_ready" as SessionState });
    expect(screen.queryByText(/아직 시안 생성이 열려 있지 않습니다/)).not.toBeInTheDocument();
  });
});

describe("오류가 아닌 것 두 가지", () => {
  it("needsInput 은 되물음으로 보인다", () => {
    setup({
      state: "brief_filling" as SessionState,
      needsInput: { field: "note", reason: "제품 사진만으로는 카테고리를 알 수 없습니다" },
    } as Partial<Session>);
    expect(screen.getByText(/카테고리를 알 수 없습니다/)).toBeInTheDocument();
    expect(screen.getByText(/요구 항목: note/)).toBeInTheDocument();
    // 오류 역할로 읽히면 안 됩니다.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("degraded 는 열화 표기로 보인다", () => {
    // ⚠️ **안내 문단 자체를 붙듭니다.** "카테고리와 타겟을 채워" 는 아래 empty-state 가
    // 내는 문구이고 그 조건은 `needsInput` 유무뿐이라, 그것만 재면 `messageMode` 블록을
    // 통째로 지워도 시험이 통과합니다(실측). 그 안내가 사라지면 사용자는 카테고리와 타겟이
    // 왜 비어 있는지 모른 채 다시 채우고, 팀은 설계된 열화(ADR-0005)를 원인 불명으로
    // 보고하게 됩니다 (PR #277 리뷰, 신호정).
    setup({ state: "brief_filling" as SessionState, messageMode: "degraded" } as Partial<Session>);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText(/자동 채움을 건너뛰고/)).toBeInTheDocument();
    expect(screen.getByText(/카테고리와 타겟을 채워/)).toBeInTheDocument();
  });

  it("degraded 가 아니면 그 안내가 없다", () => {
    // 위 시험이 "항상 보인다" 로 통과하지 않게 반대쪽을 겁니다. `messageMode` 가 실제로
    // 분기를 만드는지 여기서 갈립니다.
    setup({ state: "brief_filling" as SessionState, messageMode: "normal" } as Partial<Session>);
    expect(screen.queryByText(/자동 채움을 건너뛰고/)).not.toBeInTheDocument();
  });

  it("되물음과 열화가 다른 안내를 낸다", () => {
    // ⚠️ 둘을 가르는 근거는 `needsInput` 키의 유무입니다. 같은 문구로 합치면 되물음에
    // 답하는 자리(`note`)와 직접 채우는 자리(`category`/`target`)가 구분되지 않습니다.
    setup({
      state: "brief_filling" as SessionState,
      needsInput: { field: "note", reason: "추가 정보가 필요합니다" },
    } as Partial<Session>);
    expect(screen.getByText(/추가 메모를 채워 주세요/)).toBeInTheDocument();
    expect(screen.queryByText(/카테고리와 타겟을 채워/)).not.toBeInTheDocument();
  });
});

describe("시안 만들기 버튼", () => {
  it("진행 중에는 눌리지 않고 문구가 바뀐다", () => {
    // ⚠️ 시안 생성도 브리프를 잠그는 **되돌릴 수 없는 지점**이고(INV-7), 실물 모드에서는
    // 연타가 그대로 외부 호출 비용입니다. 확정 버튼에는 이 시험이 있었는데 여기만
    // 빠져 있었습니다 (PR #277 리뷰, 신호정).
    setup({ state: "brief_ready" as SessionState }, { pending: "draft" });
    expect(screen.getByRole("button", { name: "시안을 만드는 중..." })).toBeDisabled();
    expect(generateButton()).not.toBeInTheDocument();
  });
});

describe("확정 버튼", () => {
  it("draft_ready 에서만 나온다", () => {
    setup({ state: "draft_ready" as SessionState });
    expect(finalizeButton()).toBeInTheDocument();
    expect(screen.getByText(/세션당 한 번입니다/)).toBeInTheDocument();
  });

  it("확정된 뒤에는 사라진다", () => {
    // INV-3. 두 번째 확정은 서버가 409 로 막지만, 화면이 버튼을 두면 사용자는 눌러 봐야
    // 압니다.
    setup({ state: "finalized" as SessionState });
    expect(finalizeButton()).not.toBeInTheDocument();
  });

  it("진행 중에는 눌리지 않고 문구가 바뀐다", () => {
    setup({ state: "draft_ready" as SessionState }, { pending: "finalize" });
    const button = screen.getByRole("button", { name: "확정하는 중..." });
    expect(button).toBeDisabled();
    // 되돌릴 수 없는 행동이라 진행 중임을 문구로도 말합니다 (INV-3).
    expect(finalizeButton()).not.toBeInTheDocument();
  });
});

describe("렌더 상태", () => {
  it("잡이 없으면 확인 중이라고 말한다", () => {
    setup({ state: "rendering" as SessionState, jobId: "j1" } as Partial<Session>);
    expect(screen.getByText(/렌더 상태를 확인하고 있습니다/)).toBeInTheDocument();
  });

  it("폴링이 멈추면 확인 중이라고 말하지 않는다", () => {
    // 같은 화면의 알림이 "실패했다" 고 말하는 동안 여기가 "확인하고 있습니다" 를 띄우면
    // 두 곳이 다른 말을 합니다 (PR #248).
    setup({ state: "rendering" as SessionState, jobId: "j1" } as Partial<Session>, {
      pollingStopped: true,
    });
    expect(screen.queryByText(/렌더 상태를 확인하고 있습니다/)).not.toBeInTheDocument();
    expect(screen.getByText(/렌더 상태를 확인하지 못했습니다/)).toBeInTheDocument();
  });

  it("jobId 가 없으면 렌더 자리 자체가 없다", () => {
    setup({ state: "draft_ready" as SessionState });
    expect(screen.queryByText(/렌더 상태를/)).not.toBeInTheDocument();
  });
});

describe("실패한 세션", () => {
  it("되돌리는 경로가 없다고 말한다", () => {
    // `failed` 에서 돌아오는 간선이 없습니다 (계약의 `SessionState`).
    setup({ state: "failed" as SessionState });
    expect(screen.getByText(/새 세션으로 다시 시작해 주세요/)).toBeInTheDocument();
    expect(generateButton()).not.toBeInTheDocument();
    expect(finalizeButton()).not.toBeInTheDocument();
  });
});

describe("다시 불러오기", () => {
  it("draft_generating 에서 눌러 갱신할 수 있다", () => {
    // 다른 탭에서 시작한 생성일 수 있습니다. 화면이 추측하지 않고 다시 읽습니다.
    const props = setup({ state: "draft_generating" as SessionState });
    fireEvent.click(screen.getByRole("button", { name: "다시 불러오기" }));
    expect(props.onReload).toHaveBeenCalledTimes(1);
  });
});

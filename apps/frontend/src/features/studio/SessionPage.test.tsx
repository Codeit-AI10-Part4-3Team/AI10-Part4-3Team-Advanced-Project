import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../shared/api/client";
import type { Job, Session } from "./types";

/**
 * 세션 화면의 회귀 테스트.
 *
 * ⚠️ **여기서 고정하는 것은 "화면 두 곳이 같은 말을 하는가" 입니다.** 렌더 상태는 우측 상단
 * 알림과 오른쪽 패널 두 군데에 나타나는데, 근거가 서로 다른 값(`failure` 와 `job`)이라 한쪽만
 * 고치면 조용히 어긋납니다. 타입도 문법도 맞아 lint 와 typecheck 로는 잡히지 않습니다.
 *
 * ⚠️ `api` 를 통째로 목으로 둡니다. 실제 호출은 `e2e/` 가 봅니다 - 여기서 재는 것은 응답이
 * 왔을 때 화면이 무엇을 그리는가 하나입니다.
 */

vi.mock("./api", () => ({
  getSession: vi.fn(),
  getJob: vi.fn(),
  patchBrief: vi.fn(),
  generateDraft: vi.fn(),
  finalizeSession: vi.fn(),
  listArtStyles: vi.fn(() => Promise.resolve([])),
}));

// 401 을 로그아웃으로 옮기는 규칙(`useApiError`)은 여기 대상이 아닙니다.
vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({ signOut: vi.fn(), me: null, status: "signed_in", signIn: vi.fn() }),
}));

import * as api from "./api";
import { SessionPage } from "./SessionPage";

const RENDERING: Session = {
  sessionId: "s1",
  revision: 1,
  state: "rendering",
  outputType: "single_ad",
  jobId: "j1",
  createdAt: "2026-08-25T00:00:00Z",
  brief: {
    productName: "행복 블렌드",
    sellingPoint: "핸드드립",
    category: "식품",
    target: "30대",
    artStyle: "",
    productImageUrl: "",
  },
  briefMeta: {},
} as Session;

const RUNNING_JOB: Job = { jobId: "j1", status: "running" } as Job;

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/sessions/s1"]}>
      <Routes>
        <Route path="/sessions/:sessionId" element={<SessionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("렌더 상태 조회가 실패했을 때", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSession).mockResolvedValue(RENDERING);
  });

  it("패널이 '확인하고 있습니다' 를 계속 띄우지 않는다", async () => {
    // ⚠️ 조회 실패와 잡 실패는 다른 층입니다. 잡이 실패하면 200 이고 `ResultView` 가 그립니다.
    // 여기는 조회 자체가 안 된 경우라 화면에 잡이 없습니다.
    vi.mocked(api.getJob).mockRejectedValue(new ApiError(500, "INTERNAL", "dev"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    expect(screen.queryByText(/렌더 상태를 확인하고 있습니다/)).not.toBeInTheDocument();
    expect(screen.getByText(/렌더 상태를 확인하지 못했습니다/)).toBeInTheDocument();
  });

  it("아직 읽는 중일 때는 그대로 '확인하고 있습니다' 다", async () => {
    // 위 시험이 문구를 지우는 것만으로 통과하지 않게 반대쪽을 함께 겁니다.
    vi.mocked(api.getJob).mockReturnValue(new Promise(() => undefined));
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/렌더 상태를 확인하고 있습니다/)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("읽다가 못 읽게 돼도 '자동으로 바뀝니다' 를 계속 말하지 않는다", async () => {
    // ⚠️ **`job` 이 있는데도 멈춘 경우입니다.** `useRenderJob` 은 조회가 실패해도 직전 값을
    // 지우지 않으므로(`job: previous.job`), 몇 번 왕복한 뒤 실패하면 `job !== null` 이 먼저
    // 걸려 `ResultView` 가 그대로 그려집니다. 이 파일의 다른 시험은 전부 `job` 이 처음부터
    // `null` 인 상태로 시작해 이 경로를 지나지 않았습니다 (PR #248 리뷰, 정승호).
    //
    // ⚠️ 오히려 이쪽이 더 흔합니다. 렌더가 분 단위라 여러 번 왕복하는 동안 한 번 실패하는
    // 것이, 첫 요청부터 실패하는 것보다 자연스럽습니다 (`useRenderJob` 주석).
    vi.mocked(api.getJob)
      .mockResolvedValueOnce({ job: RUNNING_JOB, retryAfterS: 0.01 })
      .mockRejectedValue(new ApiError(500, "INTERNAL", "dev"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument(), { timeout: 3000 });

    // 마지막으로 읽은 사실은 그대로 둡니다 - 잡은 실제로 돌고 있었습니다.
    expect(screen.getByText(/이미지를 만들고 있습니다/)).toBeInTheDocument();
    // 갱신을 약속하는 문장만 사라져야 합니다.
    expect(screen.queryByText(/자동으로 바뀝니다/)).not.toBeInTheDocument();
    expect(screen.getByText(/더 이상 갱신되지 않습니다/)).toBeInTheDocument();
  });

  it("다시 시도를 누르면 옛 오류가 남지 않는다", async () => {
    // ⚠️ 되살리기는 `pollingStopped` 만 내립니다. `clear()` 가 없으면 문구는 그대로 남고
    // 재시도 버튼만 사라져, 사용자가 한 번 누른 뒤 다시 누를 방법이 없어집니다.
    vi.mocked(api.getJob)
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL", "dev"))
      .mockResolvedValue({ job: RUNNING_JOB, retryAfterS: 3600 });
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByText(/이미지를 만들고 있습니다/)).toBeInTheDocument();
  });

  it("다시 시도가 또 실패하면 알림과 버튼이 함께 돌아온다", async () => {
    // 지우기만 하고 끝나면 두 번째 실패가 조용히 지나갑니다.
    vi.mocked(api.getJob).mockRejectedValue(new ApiError(500, "INTERNAL", "dev"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "다시 시도" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

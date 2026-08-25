import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../shared/api/client";

/**
 * 로그인 복귀 (#114).
 *
 * ⚠️ **이 경로는 지금까지 도달 불가능했습니다.** `main.tsx` 의 `path="*"` 가 `RequireAuth`
 * 보다 먼저 미지의 URL 을 `/` 로 바꿔, `state.from` 이 언제나 `/` 였기 때문입니다. 그래서
 * 여기서 재는 것은 "복귀가 동작하는가" 가 아니라 **"무엇을 담아 넘기는가"** 입니다.
 *
 * ⚠️ `LoginPage` 를 직접 그리지 않고 `RequireAuth` 부터 태웁니다. 두 컴포넌트가 나눠 가진
 * 값(`state.from`)이 이 기능의 전부라, 한쪽만 보면 이어지는지 알 수 없습니다.
 */

vi.mock("./api", () => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

import * as api from "./api";
import { AuthProvider } from "./AuthProvider";
import { RequireAuth } from "./RequireAuth";
import { LoginPage } from "./LoginPage";

/**
 * 지금 라우터가 어디에 있는지 드러냅니다.
 *
 * ⚠️ `window.location` 이 아니라 `useLocation()` 입니다. `MemoryRouter` 는 브라우저 주소를
 * 건드리지 않으므로 전역을 보면 언제나 시험 러너의 주소가 나옵니다.
 */
function Here() {
  const at = useLocation();
  return <span data-testid="here">{at.pathname + at.search + at.hash}</span>;
}

function LoginWithSpy() {
  return (
    <>
      <Here />
      <LoginPage />
    </>
  );
}

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginWithSpy />} />
          <Route
            element={
              // 실제 앱과 같은 모양입니다 - `RequireAuth` 가 감싸는 것은 `<Outlet />` 을
              // 가진 껍데기(`App`)이고, 자식 경로는 그 안에서 갈아 끼워집니다.
              <RequireAuth>
                <div data-testid="protected">
                  <Outlet />
                </div>
              </RequireAuth>
            }
          >
            <Route path="/" element={<span>홈</span>} />
            <Route
              path="/sessions/:sessionId"
              element={
                <>
                  <span>세션</span>
                  <Here />
                </>
              }
            />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("미로그인으로 깊은 주소에 들어오면", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchMe).mockRejectedValue(new ApiError(401, "UNAUTHORIZED", "dev"));
  });

  it("로그인 화면으로 보낸다", async () => {
    renderAt("/sessions/abc123");
    await waitFor(() => expect(screen.getByTestId("here")).toHaveTextContent("/login"));
  });

  it("쿼리와 해시까지 담아 넘긴다", async () => {
    // ⚠️ 경로만 담으면 `?tab=render` 로 들어온 사용자가 로그인 뒤 같은 세션의 **다른
    // 화면**에 도착합니다. 돌아왔는데 보던 자리가 아닌 것이라 복귀가 없는 것보다 헷갈립니다.
    const { container } = renderAt("/sessions/abc123?tab=render#panel-2");
    await waitFor(() => expect(screen.getByTestId("here")).toHaveTextContent("/login"));

    // 로그인 성공을 흉내 내면 그 자리로 돌아가야 합니다.
    vi.mocked(api.login).mockResolvedValue({
      userId: "u1",
      loginId: "demo1",
      createdAt: "2026-08-25T00:00:00Z",
    });
    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await waitFor(() => expect(screen.getByText("세션")).toBeInTheDocument());
    expect(screen.getByTestId("here")).toHaveTextContent("/sessions/abc123?tab=render#panel-2");
  });
});

describe("돌아갈 자리로 받아 주지 않는 값", () => {
  // ⚠️ 라우터 state 는 `history` 에 실려 뒤로 가기와 새로고침을 넘어 살아남습니다. 지금은
  // 우리 코드만 이 값을 넣지만, 값이 밖에서 올 수 있게 되는 날 이 자리가 조용히 열립니다.
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchMe).mockResolvedValue({
      userId: "u1",
      loginId: "demo1",
      createdAt: "2026-08-25T00:00:00Z",
    });
  });

  /** 이미 로그인한 채로 `/login` 에 도착하면 곧바로 `from` 으로 넘어갑니다. */
  function renderSignedInAt(from: unknown) {
    return render(
      <MemoryRouter initialEntries={[{ pathname: "/login", state: { from } }]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginWithSpy />} />
            <Route path="/" element={<Here />} />
            <Route path="/sessions/:sessionId" element={<Here />} />
            <Route path="*" element={<Here />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  // ⚠️ `toHaveTextContent` 는 **부분 일치**입니다. `"/"` 로 기다리면 아직 `/login` 에 있는
  // 상태에서도 통과하고, 그다음 줄에서야 틀린 값을 보게 됩니다(실제로 그렇게 한 번 통과했습니다).
  const settledAt = (path: string) =>
    waitFor(() => expect(screen.getByTestId("here").textContent).toBe(path));

  it.each([
    ["스킴이 생략된 주소", "//evil.example/x"],
    ["절대 URL", "https://evil.example/x"],
    ["경로가 아닌 값", "sessions/abc"],
    ["문자열이 아닌 값", { pathname: "/sessions/abc" }],
  ])("%s 는 첫 화면으로 보낸다", async (_label, from) => {
    renderSignedInAt(from);
    await settledAt("/");
  });

  it("로그인 화면 자신으로는 돌려보내지 않는다", async () => {
    // 성공한 사람을 로그인 화면으로 보내면 그 화면이 다시 복귀를 시도해 왕복이 남습니다.
    renderSignedInAt("/login");
    await settledAt("/");
  });

  it("멀쩡한 경로는 그대로 받는다", async () => {
    // 위 검사가 전부를 `/` 로 보내는 것으로 통과하지 않게 반대쪽을 함께 겁니다.
    renderSignedInAt("/sessions/abc123?tab=render");
    await settledAt("/sessions/abc123?tab=render");
  });
});

describe("없는 주소", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchMe).mockRejectedValue(new ApiError(401, "UNAUTHORIZED", "dev"));
  });

  it("보호된 화면으로 새지 않는다", async () => {
    // `path="*"` 가 404 화면이 되면서 이 경로는 `RequireAuth` 를 지나지 않습니다.
    renderAt("/없는주소");
    // 잠시 기다려도 보호 경로로 새지 않습니다 - `path="*"` 가 404 화면이라 `RequireAuth`
    // 를 지나지 않고, 로그인 화면으로도 보내지 않습니다.
    await waitFor(() => expect(screen.queryByTestId("here")).not.toBeInTheDocument());
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });
});

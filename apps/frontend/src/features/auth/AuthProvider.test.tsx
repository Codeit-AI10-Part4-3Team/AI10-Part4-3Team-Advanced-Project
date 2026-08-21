import { render, screen, waitFor } from "@testing-library/react";
import { act, useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../shared/api/client";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./useAuth";
import type { Me } from "./types";

/**
 * `AuthProvider` 의 상태 전환 회귀 테스트 (#113).
 *
 * ⚠️ 여기 세 건은 전부 **고쳤지만 다시 깨져도 아무도 모르던** 것들입니다. 두 건은 늦게 도착한
 * 응답이 그 사이 확정된 상태를 덮어쓰는 경합이고(PR #102 리뷰 2번), 한 건은 처리를 마친 실패가
 * unhandled rejection 으로 남던 것입니다(PR #102 인라인 스레드).
 *
 * ⚠️ **`lint`/`typecheck`/`build` 가 잡지 못하는 부류입니다.** 타입은 맞고 문법도 맞는데 순서만
 * 틀린 것이라, 컴포넌트를 실제로 마운트하고 응답 도착 순서를 손으로 조작해야 재현됩니다.
 */

vi.mock("./api", () => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

const api = await import("./api");
const fetchMe = vi.mocked(api.fetchMe);
const login = vi.mocked(api.login);
const logout = vi.mocked(api.logout);

const ME: Me = {
  userId: "de7fa637-f372-4146-ab49-3ec9e23199f3",
  loginId: "demo1",
  createdAt: "2026-08-20T08:51:16.236641Z",
};

/** 해소 시점을 테스트가 정하는 프로미스. 응답 도착 순서를 뒤집는 데 씁니다. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  // 거절을 나중에 처리해도 unhandled 로 잡히지 않게 미리 붙여 둡니다.
  promise.catch(() => undefined);
  return { promise, resolve, reject };
}

/** 훅의 값을 DOM 으로 꺼내 옵니다. 화면이 보는 것과 같은 것만 검사합니다. */
function Probe() {
  const { status, me } = useAuth();
  return (
    <>
      <span data-testid="status">{status}</span>
      <span data-testid="login-id">{me?.loginId ?? "-"}</span>
    </>
  );
}

/**
 * `signIn` 과 `signOut` 을 테스트에서 부를 수 있게 꺼내 둡니다.
 *
 * ⚠️ **렌더 중이 아니라 효과 안에서 대입합니다.** 렌더 중 모듈 변수를 고치는 것은 부작용이고
 * (`react-hooks/globals`), 리렌더 시점에 따라 값이 달라집니다. 둘 다 `useCallback([])` 이라
 * 한 번 잡아 두면 그대로입니다.
 */
const handles: {
  signIn?: (loginId: string, password: string) => Promise<void>;
  signOut?: () => Promise<void>;
} = {};

function Handles() {
  const auth = useAuth();
  useEffect(() => {
    handles.signIn = auth.signIn;
    handles.signOut = auth.signOut;
  }, [auth.signIn, auth.signOut]);
  return null;
}

const signIn = (id: string, pw: string) => handles.signIn!(id, pw);
const signOut = () => handles.signOut!();

function mount() {
  return render(
    <AuthProvider>
      <Probe />
      <Handles />
    </AuthProvider>,
  );
}

const status = () => screen.getByTestId("status").textContent;

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("로그아웃 요청이 실패해도 던지지 않고 화면은 로그아웃된다", async () => {
    // 배경: `signOut` 이 `try`/`finally` 만 갖고 있어 거절이 호출부로 올라갔는데, 호출부가
    // `void signOut()` 이라 핸들러가 없어 unhandled rejection 이 됐습니다. 처리를 마친 실패가
    // 콘솔에는 처리되지 않은 오류로 보고되던 자리입니다 (커밋 dd31ebb).
    fetchMe.mockResolvedValue(ME);
    logout.mockRejectedValue(new ApiError(401, "UNAUTHORIZED", "로그인이 필요합니다."));
    mount();
    await waitFor(() => expect(status()).toBe("signed_in"));

    // 던지지 않는 것이 계약입니다 (`AuthContext` 의 `AuthValue` 주석). 던지면 여기서 깨집니다.
    await act(async () => {
      await expect(signOut()).resolves.toBeUndefined();
    });

    expect(status()).toBe("signed_out");
    expect(screen.getByTestId("login-id").textContent).toBe("-");
    // ⚠️ **조용한 쪽도 함께 잠급니다.** 아래 테스트가 `toHaveBeenCalled()` 만 보므로, 401
    // 판별이 사라져 경고가 **늘어나는** 방향으로는 어느 쪽도 실패하지 않습니다. 그러면 정상적인
    // 토큰 만료마다 콘솔에 경고가 쌓이고 진짜 장애의 경고가 그 사이에 묻힙니다.
    expect(console.warn).not.toHaveBeenCalled();
  });

  it("401 이 아닌 로그아웃 실패는 흔적을 남긴다", async () => {
    // 401 은 토큰이 이미 만료된 정상 경로라 조용히 넘어가지만, 그 밖의 실패는 서버에 세션이
    // 남은 채 화면만 로그아웃된 상태라 흔적이 필요합니다. 둘을 가르는 분기가 사라지면
    // 정상 동작이 매번 콘솔을 더럽히거나, 진짜 장애가 조용해집니다.
    fetchMe.mockResolvedValue(ME);
    logout.mockRejectedValue(new TypeError("Failed to fetch"));
    mount();
    await waitFor(() => expect(status()).toBe("signed_in"));

    await act(async () => {
      await signOut();
    });

    expect(status()).toBe("signed_out");
    expect(console.warn).toHaveBeenCalled();
  });

  it("마운트 시점 fetchMe 의 늦은 401 이 로그인 성공을 덮어쓰지 않는다", async () => {
    // 배경: 언마운트만 막는 플래그로는 부족했습니다. 컴포넌트는 살아 있는데 상태만
    // 갈아치워져, 로그인에 성공한 사용자가 아무 설명 없이 로그인 화면으로 되돌아갔습니다
    // (PR #102 리뷰 2번, 커밋 4b85119).
    const session = deferred<Me>();
    fetchMe.mockReturnValue(session.promise);
    login.mockResolvedValue(ME);
    mount();
    expect(status()).toBe("checking");

    // 세션 확인이 아직 도는 동안 로그인이 끝납니다.
    await act(async () => {
      await signIn("demo1", "demo-pass-1");
    });
    expect(status()).toBe("signed_in");

    // 그 뒤에야 첫 요청의 401 이 도착합니다. 세대 번호가 이것을 버려야 합니다.
    await act(async () => {
      session.reject(new ApiError(401, "UNAUTHORIZED", "로그인이 필요합니다."));
      await Promise.resolve();
    });

    expect(status()).toBe("signed_in");
    expect(screen.getByTestId("login-id").textContent).toBe("demo1");
  });

  it("로그아웃 직전 출발한 fetchMe 의 200 이 로그아웃을 되돌리지 않는다", async () => {
    // 위와 반대 방향입니다. 이쪽을 빼두면 사용자가 로그아웃 버튼을 눌렀는데 로그인 상태로
    // 남습니다 - 같은 세대 번호가 양쪽을 다 막습니다.
    const session = deferred<Me>();
    fetchMe.mockReturnValue(session.promise);
    logout.mockResolvedValue(undefined);
    mount();
    expect(status()).toBe("checking");

    await act(async () => {
      await signOut();
    });
    expect(status()).toBe("signed_out");

    // 로그아웃 뒤에 도착한 200. 되살아나면 안 됩니다.
    await act(async () => {
      session.resolve(ME);
      await Promise.resolve();
    });

    expect(status()).toBe("signed_out");
    expect(screen.getByTestId("login-id").textContent).toBe("-");
  });
});

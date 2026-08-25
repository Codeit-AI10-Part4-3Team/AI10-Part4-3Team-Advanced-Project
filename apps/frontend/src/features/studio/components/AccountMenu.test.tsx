import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountMenu } from "./AccountMenu";
import type { Me } from "../../auth/types";

/**
 * 사이드바 계정 메뉴.
 *
 * ⚠️ **여기서 고정하는 것은 "로그아웃에 닿을 수 있는가" 입니다.** 로그아웃은 이 메뉴 뒤에
 * 있는 유일한 경로라(별도 버튼이 없어졌습니다), 메뉴가 안 열리면 폰에서도 데스크톱에서도
 * 나갈 방법이 없습니다. 예전 프로필 버튼이 `onClick` 없이 살아 있던 것과 같은 종류의
 * 결함이고, 타입도 문법도 맞아 lint 와 typecheck 로는 잡히지 않습니다.
 */

const ME: Me = {
  userId: "11111111-1111-4111-8111-111111111111",
  loginId: "demo1",
  createdAt: "2026-08-13T02:30:00Z",
};

describe("AccountMenu", () => {
  it("처음에는 닫혀 있다", () => {
    render(<AccountMenu me={ME} onSignOut={() => undefined} />);
    expect(screen.queryByRole("group", { name: "계정" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "계정 메뉴" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("누르면 열리고 다시 누르면 닫힌다", () => {
    render(<AccountMenu me={ME} onSignOut={() => undefined} />);
    const trigger = screen.getByRole("button", { name: "계정 메뉴" });

    fireEvent.click(trigger);
    expect(screen.getByRole("group", { name: "계정" })).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(trigger);
    expect(screen.queryByRole("group", { name: "계정" })).not.toBeInTheDocument();
  });

  it("로그아웃을 부를 수 있다", () => {
    // 이 메뉴가 로그아웃으로 가는 유일한 길입니다. 예전의 별도 버튼은 없어졌습니다.
    const signOut = vi.fn();
    render(<AccountMenu me={ME} onSignOut={signOut} />);

    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴" }));
    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));

    expect(signOut).toHaveBeenCalledTimes(1);
    // 부르고 나면 닫힙니다. 열린 채로 두면 로그인 화면 위에 메뉴가 한 프레임 남습니다.
    expect(screen.queryByRole("group", { name: "계정" })).not.toBeInTheDocument();
  });

  it("계약이 주는 것만 보여 준다", () => {
    // ⚠️ `Me` 에는 표시 이름도 이메일도 없습니다. 두지 않기로 한 결정이라(openapi.yaml),
    // 화면이 필요하다고 필드를 먼저 만들면 그때부터 계약이 아니라 구두 합의입니다.
    render(<AccountMenu me={ME} onSignOut={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴" }));

    expect(screen.getByRole("group", { name: "계정" })).toHaveTextContent("demo1");
    expect(screen.getByText(/^가입/)).toBeInTheDocument();
  });

  it("바깥을 누르면 닫힌다", () => {
    render(<AccountMenu me={ME} onSignOut={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴" }));
    expect(screen.getByRole("group", { name: "계정" })).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole("group", { name: "계정" })).not.toBeInTheDocument();
  });

  it("Escape 로 닫으면 포커스가 버튼으로 돌아온다", () => {
    // 되돌리지 않으면 키보드 사용자가 문서 맨 앞에서 Tab 을 다시 시작하게 됩니다.
    render(<AccountMenu me={ME} onSignOut={() => undefined} />);
    const trigger = screen.getByRole("button", { name: "계정 메뉴" });
    fireEvent.click(trigger);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("group", { name: "계정" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it("트리거가 메뉴보다 DOM 앞에 있다", () => {
    // ⚠️ **동작이 아니라 구조를 검사합니다.** 위치는 `position: absolute` 가 정하므로 순서를
    // 뒤집어도 보이는 자리는 같고 스타일도 그대로입니다. 하지만 Tab 순서는 DOM 을 따라서,
    // 메뉴가 앞이면 열고 나서 Tab 을 눌러도 항목이 아니라 사이드바 밖으로 나갑니다.
    // jsdom 은 실제 Tab 이동을 재현하지 않으므로 순서 자체를 고정합니다.
    render(<AccountMenu me={ME} onSignOut={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴" }));

    const trigger = screen.getByRole("button", { name: "계정 메뉴" });
    const menu = screen.getByRole("group", { name: "계정" });
    // 4 = DOCUMENT_POSITION_FOLLOWING: 메뉴가 트리거 **뒤**에 옵니다.
    expect(trigger.compareDocumentPosition(menu) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("아직 계정을 못 읽었어도 열린다", () => {
    // `me` 는 `GET /v1/me` 가 돌아오기 전 `null` 입니다. 그때 메뉴가 막히면 조회가 실패한
    // 사용자에게 로그아웃할 길이 없어집니다.
    render(<AccountMenu me={null} onSignOut={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "계정 메뉴" }));

    expect(screen.getByRole("button", { name: "로그아웃" })).toBeInTheDocument();
    expect(screen.queryByText(/^가입/)).not.toBeInTheDocument();
  });
});

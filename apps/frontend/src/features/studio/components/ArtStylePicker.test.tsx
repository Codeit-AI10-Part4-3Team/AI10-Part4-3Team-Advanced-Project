import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeAll, describe, expect, it } from "vitest";
import { ArtStylePicker } from "./ArtStylePicker";
import type { ArtStyle } from "../types";

/**
 * 화풍 격자의 회귀 테스트.
 *
 * ⚠️ 여기서 고정하는 것은 **"크게 보는 것이 고르는 행동이 되지 않는다"** 입니다. 확대 버튼을
 * `label` 안에 두면 버튼을 눌러도 라벨이 함께 활성화되어 화풍이 선택되는데, 타입도 문법도
 * 맞아 `lint` / `typecheck` 로는 잡히지 않습니다.
 *
 * ⚠️ 포커스 가두기와 배경 비활성은 여기서 재지 않습니다. `<dialog>` 의 `showModal()` 이 하는
 * 일인데 jsdom 이 top layer 를 구현하지 않아 브라우저와 결과가 다릅니다. 그쪽은 실제 브라우저로
 * 확인했고(PR 179), 여기서 통과시키면 없는 보증을 만드는 셈입니다.
 */

const STYLES: ArtStyle[] = [
  { artStyleId: "simple-flat-webtoon", name: "심플 플랫 웹툰", exampleImageUrl: "" },
  { artStyleId: "retro-pop-art", name: "레트로 팝아트", exampleImageUrl: "/v1/example/retro" },
];

beforeAll(() => {
  // jsdom 에는 `showModal` 과 `close` 가 없습니다. **`open` 속성까지 맞춰야** 합니다 - 그것이
  // 없으면 `<dialog>` 가 접근성 트리에 올라오지 않아 `role="dialog"` 로 찾을 수 없습니다.
  const proto = window.HTMLDialogElement.prototype;
  proto.showModal ??= function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  proto.close ??= function close(this: HTMLDialogElement) {
    this.open = false;
  };
});

/** 실제 사용처와 같게 값을 부모가 들고 있습니다. */
function Harness() {
  const [value, setValue] = useState("");
  return (
    <>
      <span data-testid="value">{value === "" ? "(미선택)" : value}</span>
      <ArtStylePicker styles={STYLES} value={value} onChange={setValue} />
    </>
  );
}

const value = () => screen.getByTestId("value").textContent;

describe("ArtStylePicker", () => {
  it("후보가 비면 격자 대신 이유를 말한다", () => {
    render(<ArtStylePicker styles={[]} value="" onChange={() => undefined} />);
    expect(screen.getByText(/설정에 들어오지 않았습니다/)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("카드를 누르면 그 화풍이 선택된다", () => {
    render(<Harness />);
    expect(value()).toBe("(미선택)");
    fireEvent.click(screen.getByRole("radio", { name: /레트로 팝아트/ }));
    expect(value()).toBe("retro-pop-art");
  });

  it("예시가 없는 후보에는 확대 버튼을 만들지 않는다", () => {
    render(<Harness />);
    // 눌러 봐야 빈 화면인 버튼은 두지 않습니다. 예시가 있는 하나에만 붙습니다.
    expect(screen.getAllByRole("button", { name: /크게 보기/ })).toHaveLength(1);
    expect(screen.getByText("예시 준비 중")).toBeInTheDocument();
  });

  it("확대 버튼이 label 밖에 있다", () => {
    // ⚠️ **동작이 아니라 구조를 검사합니다.** 확대 버튼이 `label` 안으로 들어가면 실제
    // 브라우저에서는 버튼을 눌러도 라벨이 함께 활성화되어 화풍이 선택됩니다. 그런데 jsdom 은
    // 그 전파를 재현하지 않아, 클릭 후 값을 보는 테스트는 버튼을 `label` 안으로 옮겨도
    // 그대로 통과합니다(변이로 확인). 그래서 값이 아니라 위치를 고정합니다.
    render(<Harness />);
    const zoom = screen.getByRole("button", { name: /레트로 팝아트 예시 크게 보기/ });
    expect(zoom.closest("label")).toBeNull();
  });

  it("확대 버튼을 누르면 선택은 그대로고 확대창이 열린다", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /레트로 팝아트 예시 크게 보기/ }));
    expect(value()).toBe("(미선택)");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("확대창을 닫아도 선택은 그대로다", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /레트로 팝아트 예시 크게 보기/ }));
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(value()).toBe("(미선택)");
  });

  it("고른 뒤에는 선택을 해제할 수 있다", () => {
    // 라디오는 한 번 고르면 스스로 해제되지 않습니다. 해제 경로가 없으면 "미선택 시 랜덤"
    // 으로 되돌아갈 방법이 사라집니다 (F2 의 DoD).
    render(<Harness />);
    fireEvent.click(screen.getByRole("radio", { name: /레트로 팝아트/ }));
    expect(value()).toBe("retro-pop-art");
    fireEvent.click(screen.getByRole("button", { name: "선택 해제" }));
    expect(value()).toBe("(미선택)");
    expect(screen.getByText(/무작위로 채웁니다/)).toBeInTheDocument();
  });
});

/**
 * 예시 이미지 로드 실패 (#216).
 *
 * ⚠️ **여기서 재는 것은 "URL 이 있는데 그림이 없을 때"입니다.** 빈 문자열 쪽은 위에서 이미
 * 고정돼 있고, 이 블록이 없으면 그 둘이 화면에서 같아 보인다는 사실 때문에 회귀가 눈에
 * 띄지 않습니다 - 깨진 그림 아이콘은 시험이 통과하는 동안에도 떠 있을 수 있습니다.
 */
const THREE: ArtStyle[] = [
  { artStyleId: "simple-flat-webtoon", name: "심플 플랫 웹툰", exampleImageUrl: "" },
  { artStyleId: "retro-pop-art", name: "레트로 팝아트", exampleImageUrl: "/static/art-styles/a.webp" },
  { artStyleId: "soft-watercolor", name: "감성 수채화", exampleImageUrl: "/static/art-styles/b.webp" },
];

/** 카드 하나의 썸네일 `<img>`. `alt` 가 비어 있어(장식) 역할로는 찾을 수 없습니다. */
function thumb(container: HTMLElement, name: string): HTMLImageElement | null {
  const card = screen.getByRole("radio", { name: new RegExp(name) }).closest(".art-style-card");
  expect(card).not.toBeNull();
  void container;
  return card?.querySelector<HTMLImageElement>(".art-style-thumb img") ?? null;
}

describe("예시 이미지를 못 불러왔을 때 (#216)", () => {
  it("깨진 그림 대신 자리를 잡는다", () => {
    const { container } = render(
      <ArtStylePicker styles={THREE} value="" onChange={() => undefined} />,
    );
    const image = thumb(container, "레트로 팝아트");
    expect(image).not.toBeNull();

    fireEvent.error(image as HTMLImageElement);

    expect(screen.getByText("예시를 불러오지 못했습니다")).toBeInTheDocument();
    expect(thumb(container, "레트로 팝아트")).toBeNull();
  });

  it("빈 문자열과 다른 문구를 씁니다", () => {
    // 자리는 같지만 원인이 다릅니다. 2단계 전달을 하는 사람이 "아직 안 넣었나" 와 "넣었는데
    // 못 읽나" 를 구분하지 못하면 절차서의 순서 규칙(파일이 먼저, URL 이 나중)을 확인할
    // 방법이 없습니다.
    const { container } = render(
      <ArtStylePicker styles={THREE} value="" onChange={() => undefined} />,
    );
    fireEvent.error(thumb(container, "레트로 팝아트") as HTMLImageElement);

    expect(screen.getByText("예시 준비 중")).toBeInTheDocument();
    expect(screen.getByText("예시를 불러오지 못했습니다")).toBeInTheDocument();
  });

  it("실패한 카드에서는 확대 버튼이 사라진다", () => {
    const { container } = render(
      <ArtStylePicker styles={THREE} value="" onChange={() => undefined} />,
    );
    expect(screen.getAllByRole("button", { name: /크게 보기/ })).toHaveLength(2);

    fireEvent.error(thumb(container, "레트로 팝아트") as HTMLImageElement);

    // 눌러도 빈 다이얼로그인 버튼을 없애는 것이 이 이슈의 DoD 두 번째 줄입니다.
    expect(
      screen.queryByRole("button", { name: /레트로 팝아트 예시 크게 보기/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /감성 수채화 예시 크게 보기/ })).toBeInTheDocument();
  });

  it("실패가 카드마다 독립이다", () => {
    // 여덟 중 하나만 이름이 어긋나는 것이 실제로 예상되는 실패입니다. 한 장이 나머지 일곱을
    // 함께 끌어내리면 고칠 곳을 찾는 사람이 원인을 전달 전체로 오해합니다.
    const { container } = render(
      <ArtStylePicker styles={THREE} value="" onChange={() => undefined} />,
    );
    fireEvent.error(thumb(container, "레트로 팝아트") as HTMLImageElement);

    expect(thumb(container, "감성 수채화")).not.toBeNull();
    expect(screen.getAllByText("예시를 불러오지 못했습니다")).toHaveLength(1);
  });

  it("URL 이 바뀌면 다시 시도한다", () => {
    // ⚠️ **실패를 `artStyleId` 로 기억하면 이 시험이 깨집니다.** 운영자가 파일을 넣고 URL 을
    // 고쳐도 그 카드는 영영 실패로 남아, 고친 사람이 화면으로는 확인할 방법이 없습니다.
    // 실패한 것은 화풍이 아니라 그 주소입니다.
    const { container, rerender } = render(
      <ArtStylePicker styles={THREE} value="" onChange={() => undefined} />,
    );
    fireEvent.error(thumb(container, "레트로 팝아트") as HTMLImageElement);
    expect(thumb(container, "레트로 팝아트")).toBeNull();

    const fixed = THREE.map((style) =>
      style.artStyleId === "retro-pop-art"
        ? { ...style, exampleImageUrl: "/static/art-styles/retro-fixed.webp" }
        : style,
    );
    rerender(<ArtStylePicker styles={fixed} value="" onChange={() => undefined} />);

    expect(thumb(container, "레트로 팝아트")).not.toBeNull();
    expect(screen.queryByText("예시를 불러오지 못했습니다")).not.toBeInTheDocument();
  });

  it("확대창이 열린 뒤 실패해도 창은 남고 이유를 말한다", () => {
    // 스스로 닫으면 사용자는 자기가 잘못 눌렀다고 읽습니다. 격자의 썸네일은 `loading="lazy"`
    // 라 화면 밖이면 받아 본 적이 없어, 여기서 처음 실패하는 경로가 실제로 있습니다.
    render(<ArtStylePicker styles={THREE} value="" onChange={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /레트로 팝아트 예시 크게 보기/ }));

    const dialog = screen.getByRole("dialog");
    const large = dialog.querySelector("img");
    expect(large).not.toBeNull();

    fireEvent.error(large as HTMLImageElement);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("예시를 불러오지 못했습니다.")).toBeInTheDocument();
    expect(screen.getByRole("dialog").querySelector("img")).toBeNull();
  });
});

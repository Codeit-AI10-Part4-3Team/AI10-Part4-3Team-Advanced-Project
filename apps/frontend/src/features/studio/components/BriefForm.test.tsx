import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 새 세션 입력 폼.
 *
 * ⚠️ **여기서 고정하는 것은 "필수를 다 채우기 전에는 시작할 수 없다" 입니다.** 버튼이 열려
 * 있으면 서버가 422 로 막지만, 사용자에게는 눌러 봐야 아는 실패가 됩니다.
 *
 * ⚠️ 세 패널이 **한 `<form>`** 에 속한다는 것도 함께 고정합니다. 화풍 라디오가 다른 폼에
 * 갇히면 제출에서 조용히 빠지고, 세션은 만들어지는데 화풍만 미선택으로 저장됩니다.
 */

vi.mock("../api", () => ({ listArtStyles: vi.fn() }));

import { listArtStyles } from "../api";
import { BriefForm } from "./BriefForm";

const STYLES = [
  { artStyleId: "레트로 팝아트", name: "레트로 팝아트", exampleImageUrl: "" },
  { artStyleId: "감성 수채화", name: "감성 수채화", exampleImageUrl: "" },
];

function setup(onSubmit = vi.fn()) {
  render(<BriefForm onSubmit={onSubmit} pending={false} guide={<section>STEP 03 자리</section>} />);
  return { onSubmit };
}

const startButton = () => screen.getByRole("button", { name: /광고 만들기 시작/ });

/**
 * 폼을 직접 제출합니다.
 *
 * ⚠️ **버튼 클릭으로는 jsdom 에서 제출이 일어나지 않습니다.** 파일 입력에 `required` 가
 * 걸려 있는데, `fireEvent.change` 로는 `files` 만 채워지고 `value` 는 빈 문자열로 남아
 * 브라우저 검사에서 막힙니다. 실제 브라우저는 파일을 고르면 둘 다 채우므로 이 차이는
 * jsdom 쪽 한계이고, 클릭 -> 제출 경로는 Playwright 로 따로 확인했습니다.
 *
 * 그래서 버튼은 **활성 여부**로 재고(위 시험들), 제출 payload 는 여기로 잽니다.
 */
const submitForm = () => fireEvent.submit(document.querySelector("form") as HTMLFormElement);
const panel = (name: RegExp) => screen.getByRole("region", { name });

function fillRequired(file = true) {
  if (file) {
    const image = new File(["x"], "product.webp", { type: "image/webp" });
    fireEvent.change(document.querySelector("input[type=file]") as HTMLInputElement, {
      target: { files: [image] },
    });
  }
  fireEvent.change(screen.getByPlaceholderText(/행복 블렌드 커피/), {
    target: { value: "행복 블렌드 커피" },
  });
  fireEvent.change(screen.getByPlaceholderText(/무향 무알코올/), {
    target: { value: "무향 무알코올, 두꺼운 원단" },
  });
}

describe("필수 항목 표시", () => {
  beforeEach(() => vi.mocked(listArtStyles).mockResolvedValue([]));

  it("계약이 required 로 둔 세 항목에 (필수) 가 붙는다", () => {
    // ⚠️ 목록의 근거는 openapi.yaml 의 `SessionCreateRequest.required` 입니다. `outputType`
    // 은 기본값이 있어 비는 경우가 없으므로 표시하지 않습니다.
    // ⚠️ 라벨을 **문구가 아니라 폼 컨트롤로** 찾습니다. 비활성 안내가 같은 단어를 쓰기
    // 때문에(`아직 비어 있습니다: 제품명, ...`) 텍스트로 찾으면 둘 다 걸립니다.
    setup();
    for (const label of ["제품 이미지", "제품명", "제품 특징"]) {
      const field = screen.getByLabelText(new RegExp(label)).closest("label");
      expect(within(field as HTMLElement).getByText("(필수)")).toBeInTheDocument();
    }
  });

  it("선택 항목에는 붙지 않는다", () => {
    setup();
    const optional = screen.getByText("추가 메모").closest("label");
    expect(within(optional as HTMLElement).queryByText("(필수)")).not.toBeInTheDocument();
  });

  it("라벨과 안내 문구가 같은 말을 쓴다", () => {
    // ⚠️ 라벨만 "장점" 이고 안내는 "특징" 이던 때가 있었습니다 (PR #302 리뷰). 이 칸은
    // 가드레일의 근거 원문이라 "특징" 이 맞고, 둘이 어긋나면 무엇을 적을지 두 번 판단하게
    // 됩니다. 한쪽만 고치는 것을 막습니다.
    setup();
    expect(screen.getByLabelText(/제품 특징/)).toBeInTheDocument();
    expect(screen.getByText(/광고가 근거로 쓸 제품의 실제 특징을 적어주세요/)).toBeInTheDocument();
    expect(screen.queryByText(/장점/)).not.toBeInTheDocument();
  });

  it("어려운 말을 쓰지 않는다", () => {
    // "소구점" 은 업계 용어라 처음 쓰는 사람이 무엇을 적어야 할지 모릅니다. 계약의 필드
    // 이름(`sellingPoint`)은 그대로이고 바뀐 것은 화면 문구뿐입니다.
    setup();
    expect(screen.getByLabelText(/제품 특징/)).toBeInTheDocument();
    expect(screen.queryByText(/소구점/)).not.toBeInTheDocument();
  });
});

describe("시작 버튼", () => {
  beforeEach(() => vi.mocked(listArtStyles).mockResolvedValue([]));

  it("필수가 비면 눌리지 않는다", () => {
    setup();
    expect(startButton()).toBeDisabled();
    // ⚠️ **어느 칸이 비었는지 이름을 댑니다.** 버튼을 잠그면 브라우저의 `required` 안내가
    // 도달하지 못해(비활성 버튼은 클릭도 Enter 도 아무 일을 하지 않습니다), 필수 셋 중
    // 무엇이 남았는지 화면이 말하지 않으면 사용자가 스스로 찾아야 합니다.
    expect(screen.getByText(/아직 비어 있습니다: 제품 이미지, 제품명, 제품 특징/)).toBeInTheDocument();
  });

  it("안내가 스크린 리더에 전달된다", () => {
    // ⚠️ **비활성 버튼은 탭 순서에서 건너뜁니다.** 화면을 못 보는 사용자는 이 문구까지
    // 오지 못하고, `role="status"` 가 없으면 문구가 바뀌어도 알림이 없습니다 - 칸을
    // 채워 나가도 무엇이 남았는지 계속 모르게 됩니다 (PR #266 리뷰, 신호정).
    setup();
    expect(screen.getByRole("status")).toHaveTextContent(/아직 비어 있습니다/);
  });

  it("채운 것은 안내에서 빠진다", () => {
    setup();
    fireEvent.change(screen.getByPlaceholderText(/행복 블렌드 커피/), {
      target: { value: "행복 블렌드 커피" },
    });
    const hint = screen.getByText(/아직 비어 있습니다/);
    expect(hint).toHaveTextContent("제품 이미지");
    expect(hint).toHaveTextContent("제품 특징");
    expect(hint).not.toHaveTextContent("제품명,");
  });

  it("공백만 친 칸은 여전히 비어 있다고 말한다", () => {
    setup();
    fireEvent.change(screen.getByPlaceholderText(/행복 블렌드 커피/), { target: { value: "   " } });
    expect(screen.getByText(/아직 비어 있습니다/)).toHaveTextContent("제품명");
  });

  it("사진과 제품명만으로는 열리지 않는다", () => {
    setup();
    const image = new File(["x"], "product.webp", { type: "image/webp" });
    fireEvent.change(document.querySelector("input[type=file]") as HTMLInputElement, {
      target: { files: [image] },
    });
    fireEvent.change(screen.getByPlaceholderText(/행복 블렌드 커피/), {
      target: { value: "행복 블렌드 커피" },
    });
    expect(startButton()).toBeDisabled();
  });

  it("공백만 친 것은 채운 것이 아니다", () => {
    // ⚠️ 계약이 `minLength: 1` 이라 서버는 공백 하나도 받습니다. 그렇게 만든 세션은
    // 가드레일의 근거가 비어 시안이 거절되므로 화면에서 먼저 막습니다.
    setup();
    const image = new File(["x"], "product.webp", { type: "image/webp" });
    fireEvent.change(document.querySelector("input[type=file]") as HTMLInputElement, {
      target: { files: [image] },
    });
    fireEvent.change(screen.getByPlaceholderText(/행복 블렌드 커피/), { target: { value: "   " } });
    fireEvent.change(screen.getByPlaceholderText(/무향 무알코올/), { target: { value: "   " } });
    expect(startButton()).toBeDisabled();
  });

  it("필수를 다 채우면 열리고 제출된다", () => {
    const { onSubmit } = setup();
    fillRequired();
    expect(startButton()).toBeEnabled();

    submitForm();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      productName: "행복 블렌드 커피",
      sellingPoint: "무향 무알코올, 두꺼운 원단",
      outputType: "single_ad",
    });
  });

  it("필수가 비면 폼이 제출돼도 넘기지 않는다", () => {
    // 버튼을 비활성으로 두는 것과 별개로 `submit` 자체를 막습니다 - Enter 키와 브라우저
    // 확장처럼 버튼을 거치지 않는 제출 경로가 있습니다.
    const { onSubmit } = setup();
    submitForm();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("세 단계 배치", () => {
  it("STEP 01 과 STEP 02 가 같은 폼 안에 있다", async () => {
    // ⚠️ 화풍이 다른 폼에 갇히면 제출에서 조용히 빠집니다. 세션은 만들어지는데 화풍만
    // 미선택으로 저장되어, 나중에 왜 무작위로 나왔는지 알 수 없게 됩니다.
    vi.mocked(listArtStyles).mockResolvedValue(STYLES);
    setup();
    await waitFor(() => expect(screen.getByRole("radiogroup")).toBeInTheDocument());

    const form = document.querySelector("form");
    expect(form).not.toBeNull();
    expect(form).toContainElement(panel(/광고 정보 입력/));
    expect(form).toContainElement(panel(/화풍 선택/));
    expect(form).toContainElement(screen.getByRole("radiogroup"));
    // 폼이 하나뿐이어야 합니다. 둘이면 위 검사가 통과해도 제출이 갈립니다.
    expect(document.querySelectorAll("form")).toHaveLength(1);
  });

  it("고른 화풍이 제출에 실린다", async () => {
    vi.mocked(listArtStyles).mockResolvedValue(STYLES);
    const { onSubmit } = setup();
    await waitFor(() => expect(screen.getByRole("radiogroup")).toBeInTheDocument());

    fillRequired();
    fireEvent.click(screen.getByRole("radio", { name: /감성 수채화/ }));
    submitForm();

    expect(onSubmit.mock.calls[0][0]).toMatchObject({ artStyle: "감성 수채화" });
  });

  it("세 번째 칸은 받아서 놓기만 한다", () => {
    vi.mocked(listArtStyles).mockResolvedValue([]);
    setup();
    expect(screen.getByText("STEP 03 자리")).toBeInTheDocument();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultView } from "./ResultView";
import type { Job } from "../types";

/**
 * 결과 이미지 자리 (#246).
 *
 * ⚠️ **`imageUrl` 은 만료돼도 빈 문자열이 되지 않습니다.** 계약이 그렇게 못 박고 있어
 * (openapi.yaml 의 `JobResult.imageUrl`), 업로드 사진 쪽에서 쓰던 "빈 문자열로 먼저 분기"
 * 수법이 여기서는 성립하지 않습니다. 그래서 이 파일이 재는 것은 **`expiresAt` 과 `onError`
 * 두 겹이 실제로 작동하는가** 입니다.
 */

const HOUR = 60 * 60 * 1000;

function doneJob(expiresAt: string): Job {
  return {
    jobId: "j1",
    status: "done",
    result: {
      imageUrl: "/v1/jobs/j1/image",
      width: 1024,
      height: 1024,
      expiresAt,
    },
  } as Job;
}

const image = () => document.querySelector<HTMLImageElement>("img.result-image");
const saveLink = () => screen.queryByRole("link", { name: "이미지 저장" });

afterEach(() => vi.useRealTimers());

describe("보관 기간이 남아 있을 때", () => {
  it("이미지와 저장 링크를 그린다", () => {
    render(<ResultView job={doneJob(new Date(Date.now() + 24 * HOUR).toISOString())} productName="행복 블렌드" />);

    expect(image()).not.toBeNull();
    expect(saveLink()).toBeInTheDocument();
    expect(screen.getByText(/까지 내려받을 수 있습니다/)).toBeInTheDocument();
  });
});

describe("보관 기간이 지났을 때", () => {
  it("이미지를 아예 요청하지 않는다", () => {
    // ⚠️ 404 왕복 자체를 만들지 않는 것이 요점입니다. `onError` 로만 처리하면 만료된 세션을
    // 열 때마다 없는 파일을 한 번씩 부르게 됩니다.
    render(<ResultView job={doneJob(new Date(Date.now() - HOUR).toISOString())} productName="행복 블렌드" />);

    expect(image()).toBeNull();
    expect(screen.getByText(/보관 기간이 지나 이미지를 내려받을 수 없습니다/)).toBeInTheDocument();
  });

  it("저장 링크를 내린다", () => {
    // 눌러도 404 인 버튼을 남겨 두면 사용자가 자기 네트워크 문제로 읽습니다.
    render(<ResultView job={doneJob(new Date(Date.now() - HOUR).toISOString())} productName="행복 블렌드" />);

    expect(saveLink()).not.toBeInTheDocument();
  });

  it("언제까지였는지는 여전히 말한다", () => {
    render(<ResultView job={doneJob("2026-08-19T09:00:00Z")} productName="행복 블렌드" />);

    expect(screen.getByText(/2026/)).toBeInTheDocument();
  });
});

describe("기간은 남았는데 이미지를 못 불러올 때", () => {
  it("깨진 그림 대신 자리를 잡는다", () => {
    // 시계가 어긋났거나 서버가 먼저 지운 경우입니다. `expiresAt` 만으로는 안 걸립니다.
    render(<ResultView job={doneJob(new Date(Date.now() + 24 * HOUR).toISOString())} productName="행복 블렌드" />);

    fireEvent.error(image() as HTMLImageElement);

    expect(image()).toBeNull();
    expect(saveLink()).not.toBeInTheDocument();
    expect(screen.getByText(/보관 기간이 지나 이미지를 내려받을 수 없습니다/)).toBeInTheDocument();
  });
});

describe("못 읽는 `expiresAt`", () => {
  it("만료로 치지 않고 그려 본다", () => {
    // ⚠️ 판정을 못 한 것과 지난 것은 다릅니다. 앞을 뒤로 읽으면 멀쩡한 이미지를 화면이
    // 먼저 숨기고, 사용자는 있는 결과를 못 받습니다. 그때는 `onError` 에 맡깁니다.
    render(<ResultView job={doneJob("나중에")} productName="행복 블렌드" />);

    expect(image()).not.toBeNull();
    expect(saveLink()).toBeInTheDocument();
  });
});

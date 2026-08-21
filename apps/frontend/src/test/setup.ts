import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
// Testing Library 의 DOM 단언(`toBeInTheDocument` 등)을 등록합니다.
import "@testing-library/jest-dom/vitest";

// ⚠️ **자동 정리가 아닙니다.** Testing Library 는 `globals: true` 일 때만 스스로 `afterEach` 에
// 붙습니다. 이 저장소는 `describe`/`it`/`expect` 를 명시적으로 import 하는 쪽이라 여기서 겁니다.
// 없으면 이전 테스트의 렌더가 DOM 에 남아 `getByTestId` 가 "여러 개 찾음" 으로 깨집니다.
afterEach(cleanup);

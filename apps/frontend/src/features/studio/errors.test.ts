import { describe as group, expect, it } from "vitest";
import { ApiError } from "../../shared/api/client";
import { describe, describeCode } from "./errors";
import type { FailureKind } from "./errors";
import type { ErrorCode } from "./types";

/**
 * 기획서 12.5 의 실패 5 종이 각각 구분되는지 고정합니다 (F10 의 DoD).
 *
 * ⚠️ **딱지가 서로 달라야 "구분" 입니다.** 다섯이 전부 문구만 다르고 같은 이름으로 묶이면
 * 사용자는 여전히 어느 실패인지 모릅니다. 그래서 문구 존재가 아니라 **딱지가 다섯 가지로
 * 갈리는지**를 검사합니다.
 *
 * ⚠️ 문구 원문은 검사하지 않습니다. 배포 단계에서 사용자용으로 다시 쓰기로 되어 있어
 * (기획서 12.5, 17 절) 지금 문장을 고정하면 그 작업이 테스트 수정부터 시작하게 됩니다.
 */

/** 기획서 12.5 의 다섯 줄과 1:1 입니다. */
const FIVE: { code: ErrorCode; label: string }[] = [
  { code: "GENERATION_TIMEOUT", label: "생성 시간 초과" },
  { code: "CONTENT_POLICY_REJECTED", label: "콘텐츠 정책 거절" },
  { code: "INSUFFICIENT_INPUT", label: "입력 정보 부족" },
  { code: "INVALID_IMAGE", label: "규격 오류" },
  { code: "UPSTREAM_UNAVAILABLE", label: "호출 실패" },
];

group("실패 5종 구분", () => {
  it.each(FIVE)("$code 는 '$label' 로 구분된다", ({ code, label }) => {
    const result = describeCode(code, "서버 개발용 문구");
    expect(result.label).toBe(label);
    expect(result.code).toBe(code);
    // 서버의 개발용 문구가 그대로 새어 나가면 안 됩니다 (기획서 17.2).
    expect(result.message).not.toBe("서버 개발용 문구");
    expect(result.message.length).toBeGreaterThan(0);
  });

  it("다섯의 딱지가 서로 다르다", () => {
    const labels = FIVE.map(({ code }) => describeCode(code, "").label);
    expect(new Set(labels).size).toBe(5);
  });

  it("5종이 아닌 코드에는 딱지가 없다", () => {
    // 딱지의 없음 자체가 "실패가 아니라 상태가 어긋난 것" 이라는 표시입니다.
    for (const code of ["NOT_FOUND", "STATE_CONFLICT", "REVISION_CONFLICT"] as ErrorCode[]) {
      const result = describeCode(code, "서버 개발용 문구");
      expect(result.label).toBeUndefined();
      expect(result.message).not.toBe("서버 개발용 문구");
    }
  });

  it("표에 없는 코드는 서버 문구로 떨어진다", () => {
    // 침묵보다는 낫습니다. 화면이 아무 말도 못 하는 것이 가장 나쁩니다.
    const result = describeCode("RATE_LIMITED" as ErrorCode, "서버 개발용 문구");
    expect(result.message).toBe("서버 개발용 문구");
    expect(result.label).toBeUndefined();
  });
});

group("describe", () => {
  it("ApiError 는 코드로 갈린다", () => {
    const result = describe(new ApiError(504, "GENERATION_TIMEOUT", "dev"));
    expect(result.label).toBe("생성 시간 초과");
    expect(result.code).toBe("GENERATION_TIMEOUT");
  });

  it("응답이 없으면 호출 실패로 본다", () => {
    // `ApiError` 는 응답을 받은 뒤에만 만들어집니다. 그것이 아니면 서버에 닿지도 못한 것이라
    // 기획서 12.5 의 "호출 실패" 입니다. 코드가 없는 것이 정상입니다.
    const result = describe(new TypeError("Failed to fetch"));
    expect(result.label).toBe("호출 실패");
    expect(result.code).toBeUndefined();
  });
});

/** 타입이 5 종을 벗어나면 컴파일에서 걸립니다. 런타임 검사가 아니라 표시용입니다. */
const _kinds: FailureKind[] = ["timeout", "policy", "insufficient", "invalid", "unreachable"];
void _kinds;

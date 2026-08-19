import { useCallback, useState } from "react";
import { ApiError } from "../../shared/api/client";
import { useAuth } from "../auth/useAuth";
import type { ErrorCode } from "./types";

/**
 * 오류 코드에서 화면 문구로.
 *
 * ⚠️ **서버의 `message` 는 개발용입니다** (기획서 17.2). 원인 파악이 목적이라 사용자에게
 * 그대로 보이면 내부 사정이 노출되고 다음 행동도 알려 주지 못합니다. 그래서 화면은 `code` 로
 * 분기하고, 여기에 없는 코드일 때만 서버 문구를 그대로 씁니다 - 침묵보다는 낫기 때문입니다.
 *
 * 여기 있는 것은 관통 경로에서 실제로 도달 가능한 코드뿐입니다. 기획서 12.5의 실패 5종을
 * 각각 구분해 보여 주는 것은 F10 의 몫이며(06 일정 08-26), 그때 이 표가 그 목록으로
 * 채워집니다.
 */
const MESSAGES: Partial<Record<ErrorCode, string>> = {
  INVALID_IMAGE:
    "이미지 규격을 확인해 주세요. JPEG, PNG, WebP 만 받고 최대 10MB, 짧은 변이 512px 이상이어야 합니다.",
  INVALID_REQUEST: "입력값을 다시 확인해 주세요.",
  NOT_FOUND: "세션을 찾을 수 없습니다. 이미 만료되었거나 삭제된 세션입니다.",
  CONTENT_POLICY_REJECTED:
    "입력한 제품 정보만으로는 광고 문구의 근거가 부족합니다. 핵심 소구점을 더 구체적으로 적어 주세요.",
  UPSTREAM_UNAVAILABLE: "생성 엔진에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  GENERATION_TIMEOUT: "생성이 제한 시간을 넘겼습니다. 다시 시도해 주세요.",
  STATE_CONFLICT: "이미 진행된 단계입니다. 최신 상태를 다시 불러옵니다.",
  REVISION_CONFLICT: "다른 곳에서 먼저 수정되었습니다. 최신 상태를 다시 불러옵니다.",
  INTERNAL: "서버에서 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
};

/**
 * 코드 하나를 문구로. HTTP 오류와 **잡 실패 양쪽이 같은 표를 씁니다** - 화면이 어느 경로로
 * 왔든 같은 분기를 타야 하기 때문이고, 그것이 `CONTENT_POLICY_REJECTED` 와
 * `GENERATION_TIMEOUT` 이 두 곳에 다 있는 이유입니다 (계약의 `Job.error`).
 */
export function describeCode(code: ErrorCode, fallback: string): string {
  return MESSAGES[code] ?? fallback;
}

export function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return describeCode(error.code as ErrorCode, error.message);
  }
  // 네트워크 실패 · 프록시 부재 등 응답 자체가 없는 경우입니다. `ApiError` 가 아니므로
  // 코드도 없고, 사용자가 할 수 있는 일은 연결을 확인하는 것뿐입니다.
  return "서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.";
}

/**
 * 화면 하나가 들고 다니는 오류 상태.
 *
 * ⚠️ **401 은 문구로 보여 주지 않고 로그아웃합니다.** 토큰 수명이 24시간이고 갱신 경로가
 * 없어서(세션_보관_정책 1.4절), 만료된 뒤에는 무엇을 눌러도 401 입니다. 그 화면에 "인증
 * 오류입니다"를 띄워 두면 사용자는 계속 눌러 볼 뿐이고 로그인 화면으로 가는 길이 없습니다.
 * `signOut` 은 던지지 않으므로(`AuthContext`) 여기서 `void` 로 부르는 것이 안전합니다.
 */
export function useApiError() {
  const { signOut } = useAuth();
  const [message, setMessage] = useState<string | null>(null);

  const report = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        void signOut();
        return;
      }
      setMessage(describe(error));
    },
    [signOut],
  );

  const clear = useCallback(() => setMessage(null), []);

  return { message, report, clear };
}

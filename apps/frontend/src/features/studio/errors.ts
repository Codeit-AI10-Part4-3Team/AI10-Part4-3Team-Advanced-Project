import { useCallback, useState } from "react";
import { ApiError } from "../../shared/api/client";
import { useAuth } from "../auth/useAuth";
import type { ErrorCode } from "./types";

/**
 * 기획서 12.5 가 나열한 **실패 5종**입니다. 화면이 다섯을 구분해 보여 주는 것이 F10 이고,
 * 그 목적은 "어느 단계에서 무엇 때문에 실패했는지 즉시 확인" 입니다 (같은 절).
 *
 * ⚠️ **묶는 기준은 사용자가 다음에 할 일입니다.** 코드가 달라도 할 일이 같으면 한 종으로
 * 묶고, 같은 코드라도 할 일이 갈리면 나눕니다. 코드를 그대로 다섯 줄 늘어놓으면 사용자는
 * 여전히 무엇을 해야 할지 모릅니다.
 *
 * ⚠️ 여기 없는 코드는 5 종이 아닙니다. `NOT_FOUND` 나 `STATE_CONFLICT` 처럼 실패가 아니라
 * 상태가 어긋난 경우이고, 아래 `OTHER_MESSAGES` 가 따로 답합니다.
 */
export type FailureKind = "timeout" | "policy" | "insufficient" | "invalid" | "unreachable";

interface Failure {
  kind: FailureKind;
  /** 어느 종인지 한눈에 가르는 딱지입니다. 문구를 다 읽지 않아도 구분되게 합니다. */
  label: string;
  /** 무슨 일이 있었고 다음에 무엇을 하면 되는지. */
  message: string;
}

const FAILURES: Partial<Record<ErrorCode, Failure>> = {
  GENERATION_TIMEOUT: {
    kind: "timeout",
    label: "생성 시간 초과",
    message: "제한 시간 안에 결과가 오지 않았습니다. 잠시 후 다시 시도해 주세요.",
  },
  CONTENT_POLICY_REJECTED: {
    kind: "policy",
    label: "콘텐츠 정책 거절",
    message:
      "입력한 제품 정보만으로는 광고 문구의 근거가 부족합니다. 제품 장점을 더 구체적으로 적어 주세요.",
  },
  // ⚠️ 계약에는 있지만 **백엔드가 아직 던지지 않습니다.** 재입력 후에도 추론이 실패했을 때
  // 언제 포기할지가 미결정이라(미결정_대장 B-11, 확정 근거는 회의록) 발생 지점이 비어
  // 있습니다. 그래도 여기 두는 이유는, 그날 코드가 오면 화면이 이미 답할 수 있어야 하기
  // 때문입니다 - 없으면 서버의 개발용 문구가 그대로 사용자에게 나갑니다.
  INSUFFICIENT_INPUT: {
    kind: "insufficient",
    label: "입력 정보 부족",
    message:
      "추가 정보로도 브리프를 채우지 못했습니다. 이 세션은 이어갈 수 없으니 새 세션으로 다시 시작해 주세요.",
  },
  INVALID_IMAGE: {
    kind: "invalid",
    label: "규격 오류",
    message:
      "이미지 규격을 확인해 주세요. JPEG, PNG, WebP 만 받고 최대 10MB, 짧은 변이 512px 이상이어야 합니다.",
  },
  UPSTREAM_UNAVAILABLE: {
    kind: "unreachable",
    label: "호출 실패",
    message: "생성 엔진에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  },
};

/**
 * 응답 자체가 없을 때. `ApiError` 는 응답을 받은 뒤에만 만들어지므로 코드가 없습니다.
 * 기획서 12.5 의 "호출 실패 - 네트워크나 인증 오류" 중 네트워크 쪽입니다 (인증은 401 이고
 * 아래 `useApiError` 가 로그아웃으로 보냅니다).
 */
const NETWORK_FAILURE: Failure = {
  kind: "unreachable",
  label: "호출 실패",
  message: "서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.",
};

/**
 * 5 종이 아닌 코드들. 실패라기보다 **상태가 어긋난** 경우라 딱지를 붙이지 않습니다.
 *
 * ⚠️ **서버의 `message` 는 개발용입니다** (기획서 17.2). 원인 파악이 목적이라 사용자에게
 * 그대로 보이면 내부 사정이 노출되고 다음 행동도 알려 주지 못합니다. 그래서 화면은 `code` 로
 * 분기하고, 여기에도 없는 코드일 때만 서버 문구를 그대로 씁니다 - 침묵보다는 낫기 때문입니다.
 */
const OTHER_MESSAGES: Partial<Record<ErrorCode, string>> = {
  INVALID_REQUEST: "입력값을 다시 확인해 주세요.",
  NOT_FOUND: "세션을 찾을 수 없습니다. 이미 만료되었거나 삭제된 세션입니다.",
  STATE_CONFLICT: "이미 진행된 단계입니다. 최신 상태를 다시 불러옵니다.",
  REVISION_CONFLICT: "다른 곳에서 먼저 수정되었습니다. 최신 상태를 다시 불러옵니다.",
  INTERNAL: "서버에서 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
};

/** 화면이 오류 하나를 그리는 데 필요한 전부입니다. */
export interface Described {
  /** 5 종 중 하나일 때만 있습니다. */
  label?: string;
  message: string;
  /** 개발 단계에서 "무엇 때문에" 를 즉시 알기 위한 값입니다 (기획서 12.5). */
  code?: ErrorCode;
}

/**
 * 코드 하나를 화면에 그릴 것으로. HTTP 오류와 **잡 실패 양쪽이 같은 표를 씁니다** - 화면이
 * 어느 경로로 왔든 같은 분기를 타야 하기 때문이고, 그것이 `CONTENT_POLICY_REJECTED` 와
 * `GENERATION_TIMEOUT` 이 두 곳에 다 있는 이유입니다 (계약의 `Job.error`).
 */
export function describeCode(code: ErrorCode, fallback: string): Described {
  const failure = FAILURES[code];
  if (failure !== undefined) {
    return { label: failure.label, message: failure.message, code };
  }
  return { message: OTHER_MESSAGES[code] ?? fallback, code };
}

export function describe(error: unknown): Described {
  if (error instanceof ApiError) {
    return describeCode(error.code as ErrorCode, error.message);
  }
  // 응답 자체가 없는 경우입니다. `ApiError` 는 응답을 받은 뒤에만 만들어지므로 코드가 없습니다.
  return { label: NETWORK_FAILURE.label, message: NETWORK_FAILURE.message };
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
  const [failure, setFailure] = useState<Described | null>(null);

  const report = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        void signOut();
        return;
      }
      setFailure(describe(error));
    },
    [signOut],
  );

  const clear = useCallback(() => setFailure(null), []);

  return { failure, report, clear };
}

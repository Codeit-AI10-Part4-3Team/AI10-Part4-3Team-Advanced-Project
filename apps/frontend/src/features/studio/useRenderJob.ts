import { useCallback, useEffect, useRef, useState } from "react";
import { getJob } from "./api";
import type { Job } from "./types";

/**
 * 서버가 `Retry-After` 를 안 실었을 때만 쓰는 값입니다.
 *
 * ⚠️ 이것은 **기본 폴링 간격이 아닙니다.** 간격의 주인은 서버이고(계약의 `Retry-After`),
 * 이 상수는 헤더가 없을 때 폴링이 아예 멈추는 것을 막는 하한일 뿐입니다. 여기 값을 올려
 * 부하를 조절하려 들면 서버가 정한 간격과 둘이 싸웁니다.
 */
const FALLBACK_INTERVAL_S = 3;

interface JobSnapshot {
  job: Job | null;
  error: unknown;
}

interface RenderJobState extends JobSnapshot {
  /** 조회 실패로 멈춘 폴링을 다시 시작합니다. 화면이 사용자에게 내주는 유일한 복구 경로입니다. */
  retry: () => void;
}

/**
 * 잡 하나를 끝날 때까지 따라갑니다. `jobId` 가 없으면 아무것도 하지 않습니다 (확정 전).
 *
 * ⚠️ **`jobId` 는 세션에서 옵니다** - 화면이 따로 보관하지 않습니다. 그래서 새로고침해도,
 * 브라우저를 닫았다 다시 열어도 `GET /v1/sessions/{id}` 한 번이면 진행 중인 렌더로 돌아옵니다.
 * `localStorage` 에 담아 두는 쪽은 두 사본이 어긋나는 경우를 새로 만듭니다.
 *
 * `onSettled` 는 `done` · `failed` 에 도달했을 때 한 번 불립니다. 잡의 종료와 세션의 상태
 * 전이는 다른 층이라(용어_사전.md 1.4절) 세션을 다시 읽는 것은 호출부의 몫입니다.
 *
 * ⚠️ 조회가 실패하면 폴링은 멈추고 `retry` 를 부를 때까지 다시 시작하지 않습니다. 렌더는 분
 * 단위라(#116 실측 55 ~ 311 초) 그 사이 일시적 실패가 드물지 않은데, 되살릴 방법이 없으면
 * 화면이 영영 멈춘 채로 남습니다.
 */
export function useRenderJob(jobId: string | undefined, onSettled?: () => void): RenderJobState {
  const [state, setState] = useState<JobSnapshot>({ job: null, error: null });

  // 폴링 세대. `jobId` 가 그대로여도 이 값이 바뀌면 효과가 다시 돌아 폴링이 살아납니다.
  const [attempt, setAttempt] = useState(0);

  // 콜백이 매 렌더 새로 만들어져도 폴링이 다시 시작되지 않게 합니다. 이것을 `useEffect` 의
  // 의존성에 그대로 넣으면 부모가 리렌더될 때마다 폴링 루프가 처음부터 다시 돕니다.
  const settledRef = useRef(onSettled);
  useEffect(() => {
    settledRef.current = onSettled;
  }, [onSettled]);

  useEffect(() => {
    if (jobId === undefined) {
      setState({ job: null, error: null });
      return;
    }

    // StrictMode 는 효과를 두 번 실행합니다. 취소 플래그가 없으면 첫 번째 루프가 정리된 뒤에도
    // 계속 돌아 폴링이 두 배로 나갑니다.
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const { job, retryAfterS } = await getJob(jobId);
        if (cancelled) return;
        setState({ job, error: null });

        if (job.status === "queued" || job.status === "running") {
          timer = window.setTimeout(() => void poll(), (retryAfterS ?? FALLBACK_INTERVAL_S) * 1000);
          return;
        }
        settledRef.current?.();
      } catch (error: unknown) {
        if (cancelled) return;
        // 폴링을 멈춥니다. 조회 자체가 실패한 것이라(잡 실패는 200 입니다) 계속 두드려도
        // 같은 답이 올 수 있어, 다시 두드릴지는 사용자가 정합니다 (`retry`).
        setState((current) => ({ ...current, error }));
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [jobId, attempt]);

  // 오류를 먼저 지웁니다. 새 조회가 돌아오기 전까지 배너를 남겨 두면 눌러도 아무 일이
  // 없는 것처럼 보입니다.
  const retry = useCallback(() => {
    setState((current) => ({ ...current, error: null }));
    setAttempt((generation) => generation + 1);
  }, []);

  return { ...state, retry };
}

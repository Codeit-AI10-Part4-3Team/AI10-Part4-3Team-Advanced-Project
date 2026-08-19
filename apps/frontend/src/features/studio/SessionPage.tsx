import { useCallback, useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { finalizeSession, generateDraft, getSession } from "./api";
import { BriefSummary } from "./components/BriefSummary";
import { DraftPanel } from "./components/DraftPanel";
import { describe, useApiError } from "./errors";
import { useRenderJob } from "./useRenderJob";
import type { Session } from "./types";

/**
 * 세션 하나의 전 구간: 브리프 확인 -> 시안 -> 확정 -> 렌더 -> 결과.
 *
 * ⚠️ **진행 상태를 화면이 보관하지 않습니다.** `sessionId` 는 URL 에, `jobId` 는 세션에
 * 있으므로 새로고침해도 브라우저를 닫았다 열어도 이 화면 하나가 같은 곳으로 돌아옵니다.
 * 화면에 사본을 두면 그 사본과 서버가 어긋나는 경우를 새로 만들게 됩니다.
 */
export function SessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  if (sessionId === undefined) return <Navigate to="/" replace />;

  // ⚠️ `key` 로 세션마다 컴포넌트를 새로 만듭니다. 다른 세션으로 이동할 때 이전 세션의
  // 브리프가 한 프레임 남는 것을 막는 방법이 둘인데(효과 안에서 상태를 지우기, key),
  // 앞의 것은 렌더를 한 번 더 돌리고 리액트가 권하지도 않습니다.
  return <SessionView key={sessionId} sessionId={sessionId} />;
}

function SessionView({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<"draft" | "finalize" | null>(null);
  const { message, report, clear } = useApiError();

  // ⚠️ 프로미스를 **반환합니다.** 호출부가 `await` 로 갱신을 기다릴 수 있어야 합니다 -
  // 기다리지 않으면 버튼이 새 상태보다 먼저 풀립니다 (아래 `run` 참고).
  const reload = useCallback(() => {
    return getSession(sessionId)
      .then((next) => {
        setSession(next);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        setLoadError(describe(error));
      });
  }, [sessionId]);

  useEffect(() => void reload(), [reload]);

  // 잡이 끝나면 세션을 다시 읽습니다. 잡의 `done` 과 세션의 `completed` 는 다른 층이고
  // (용어_사전.md 1.4절), 세션 쪽 전이는 서버가 별도로 기록하므로 화면이 추측하지 않습니다.
  const { job, error: jobError, retry: retryJob } = useRenderJob(session?.jobId, reload);

  const run = async (kind: "draft" | "finalize") => {
    clear();
    setPending(kind);
    try {
      if (kind === "draft") {
        setSession(await generateDraft(sessionId));
      } else {
        await finalizeSession(sessionId);
        // 확정 응답은 `jobId` 와 `statusUrl` 뿐입니다. 세션의 새 상태는 다시 읽어서 받습니다 -
        // 응답에 없는 것을 화면이 지어내면 서버가 실제로 어디까지 갔는지와 어긋납니다.
        //
        // ⚠️ **기다려야 합니다.** 확정 버튼이 사라지는 근거는 `session.state` 이고 그것은 이
        // GET 이 돌아와야 바뀝니다. 기다리지 않고 `pending` 을 풀면 그 왕복 동안 버튼이 다시
        // 눌리고, 사용자는 한 번만 한 행동에 "이미 진행된 단계입니다" 를 받습니다. 서버가
        // 두 번째 확정을 409 로 막으므로(INV-3) 비용 문제는 아니지만, 화면이 거짓말을 합니다.
        await reload();
      }
    } catch (error: unknown) {
      report(error);
      // 실패의 종류에 따라 서버 쪽 상태가 달라집니다 (시안 생성 실패는 `brief_ready` 로
      // 되돌리고 잠금을 풀며, 확정 충돌은 아무것도 바꾸지 않습니다). 어느 쪽인지 화면이
      // 계산하지 않고 다시 읽습니다.
      await reload();
    } finally {
      setPending(null);
    }
  };

  if (loadError !== null) {
    return (
      <header className="workspace-header">
        <div>
          <p className="eyebrow">SESSION</p>
          <h1>{loadError}</h1>
        </div>
      </header>
    );
  }

  if (session === null) {
    return <p className="workspace-loading">세션을 불러오고 있습니다...</p>;
  }

  return (
    <>
      <header className="workspace-header">
        <div>
          <p className="eyebrow">AI CREATIVE STUDIO</p>
          <h1>{session.brief.productName}</h1>
        </div>
      </header>

      {message !== null && (
        <p className="workspace-error" role="alert">
          {message}
        </p>
      )}
      {jobError !== null && (
        <p className="workspace-error" role="alert">
          {describe(jobError)} 상태 조회가 멈췄습니다.{" "}
          {/* 멈춘 폴링을 되살리는 유일한 경로입니다. 새로고침으로도 되지만 그것은 사용자가
              알아내야 하는 방법이라, 화면이 물어야 할 자리를 여기서 만듭니다. */}
          <button type="button" className="link-button" onClick={retryJob}>
            다시 시도
          </button>
        </p>
      )}

      <div className="workspace-grid">
        <BriefSummary session={session} />
        <DraftPanel
          session={session}
          job={job}
          pending={pending}
          onGenerate={() => void run("draft")}
          onFinalize={() => void run("finalize")}
          onReload={() => void reload()}
        />
      </div>
    </>
  );
}

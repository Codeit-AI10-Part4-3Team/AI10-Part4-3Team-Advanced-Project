import { useCallback, useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { finalizeSession, generateDraft, getSession, patchBrief } from "./api";
import { BriefSummary } from "./components/BriefSummary";
import { DraftPanel } from "./components/DraftPanel";
import { describe, useApiError } from "./errors";
import { ErrorNotice } from "./components/ErrorNotice";
import { useRenderJob } from "./useRenderJob";
import type { BriefPatch, Session, SessionState } from "./types";

/**
 * 브리프를 아직 고칠 수 있는 상태.
 *
 * ⚠️ **시안이 생기는 순간 잠깁니다** (INV-7). 시안은 브리프에서 나온 산출물이라 근거가 나중에
 * 바뀌면 시안이 무엇에 근거했는지 알 수 없게 됩니다. 서버가 409 `STATE_CONFLICT` 로 막지만
 * (실측 확인), 화면이 그것에 기대면 사용자는 눌러 봐야 금지를 알게 됩니다.
 */
const BRIEF_EDITABLE_STATES: ReadonlySet<SessionState> = new Set<SessionState>([
  "brief_filling",
  "brief_ready",
]);

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
  const { failure, report, clear } = useApiError();

  // ⚠️ 프로미스를 **반환합니다.** 호출부가 `await` 로 갱신을 기다릴 수 있어야 합니다 -
  // 기다리지 않으면 버튼이 새 상태보다 먼저 풀립니다 (아래 `run` 참고).
  const reload = useCallback(() => {
    return getSession(sessionId)
      .then((next) => {
        setSession(next);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        setLoadError(describe(error).message);
      });
  }, [sessionId]);

  useEffect(() => void reload(), [reload]);

  // 잡이 끝나면 세션을 다시 읽습니다. 잡의 `done` 과 세션의 `completed` 는 다른 층이고
  // (용어_사전.md 1.4절), 세션 쪽 전이는 서버가 별도로 기록하므로 화면이 추측하지 않습니다.
  //
  // ⚠️ 조회 실패는 `report` 로 넘깁니다. 폴링만 따로 문구를 만들면 401 이 로그아웃을 거치지
  // 않고 배너로 남아, 만료된 사용자가 `다시 시도` 를 눌러도 같은 화면만 다시 봅니다.
  const {
    job,
    stopped: pollingStopped,
    retry: retryJob,
  } = useRenderJob(session?.jobId, reload, report);

  /**
   * 브리프 부분 교체. 응답이 새 세션이므로 다시 읽지 않고 그대로 씁니다 - `revision` 이 이미
   * 1 올라가 있어, 여기서 `reload()` 를 부르면 왕복만 하나 늘고 값은 같습니다.
   *
   * ⚠️ **오류를 다시 던집니다.** 삼키면 편집 폼이 저장에 성공한 줄 알고 닫히고, 사용자가 방금
   * 친 값이 사라집니다. 문구는 `report` 가 만들고 폼을 열어 두는 것은 폼의 몫입니다.
   */
  const saveBrief = async (patch: BriefPatch) => {
    clear();
    try {
      setSession(await patchBrief(sessionId, session?.revision ?? 0, patch));
    } catch (error: unknown) {
      report(error);
      // 충돌(`REVISION_CONFLICT`)이면 화면이 든 `revision` 이 이미 뒤처진 것이라, 다시 읽어
      // 두어야 사용자가 같은 값으로 한 번 더 눌렀을 때 통합니다. 폼이 다시 눌릴 수 있게 되기
      // **전에** 갱신이 끝나야 하므로 기다립니다.
      await reload();
      throw error;
    }
  };

  /**
   * 멈춘 폴링을 되살립니다.
   *
   * ⚠️ **`clear()` 가 함께 있어야 합니다.** 되살리기는 `pollingStopped` 만 내리므로, 이것이
   * 없으면 알림에 **옛 오류 문구는 그대로 남고 재시도 버튼만 사라집니다**(아래 `retry` 조건이
   * `pollingStopped` 라서입니다). 사용자는 한 번 누른 뒤 같은 문구를 보면서 다시 누를 방법이
   * 없어지고, 남는 길은 새로고침뿐입니다 (실측 확인).
   */
  const retryPolling = () => {
    clear();
    retryJob();
  };

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

      {/* 하나만 띄웁니다. 둘로 나누면 같은 실패에 상자가 두 개 뜹니다. 내용은 `report` 가
          만들고 401 은 여기 오지 않습니다 - 그쪽은 로그아웃으로 갑니다(`useApiError`).
          `pollingStopped` 를 조건에 함께 둔 것은 `clear()` 로 내용이 지워져도 복구 버튼은
          남아야 하기 때문입니다. */}
      {(failure !== null || pollingStopped) && (
        <ErrorNotice
          failure={
            failure ?? { label: "호출 실패", message: "렌더 상태 조회가 멈췄습니다." }
          }
          onDismiss={clear}
          retry={pollingStopped ? { label: "다시 시도", onClick: retryPolling } : undefined}
        />
      )}

      <div className="workspace-grid">
        <BriefSummary
          session={session}
          editable={BRIEF_EDITABLE_STATES.has(session.state)}
          onSave={saveBrief}
        />
        <DraftPanel
          session={session}
          job={job}
          // ⚠️ 이것이 없으면 패널이 **거짓말을 합니다.** 조회가 실패해 폴링이 멈춘 뒤에도
          // `job` 은 `null` 이라, 패널만 보면 "확인하고 있습니다" 가 계속 떠 있습니다 -
          // 같은 화면의 알림은 실패했다고 말하는 중입니다 (실측 확인).
          pollingStopped={pollingStopped}
          pending={pending}
          onGenerate={() => void run("draft")}
          onFinalize={() => void run("finalize")}
          onReload={() => void reload()}
        />
      </div>
    </>
  );
}

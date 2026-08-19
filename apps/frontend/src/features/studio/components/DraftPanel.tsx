import { SESSION_STATE_LABEL } from "../labels";
import type { Job, Session } from "../types";
import { DraftView } from "./DraftView";
import { ResultView } from "./ResultView";

interface DraftPanelProps {
  session: Session;
  job: Job | null;
  pending: "draft" | "finalize" | null;
  onGenerate: () => void;
  onFinalize: () => void;
  onReload: () => void;
}

const READY_STATES = new Set(["draft_ready", "finalized", "rendering", "completed", "failed"]);

export function DraftPanel({
  session,
  job,
  pending,
  onGenerate,
  onFinalize,
  onReload,
}: DraftPanelProps) {
  const { state, draft, needsInput, messageMode } = session;

  return (
    <section className="panel draft-panel" aria-labelledby="draft-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">STEP 02</p>
          <h2 id="draft-heading">시안 · 확정 · 결과</h2>
        </div>
        <span className={`status-chip ${READY_STATES.has(state) ? "ready" : ""}`}>
          {SESSION_STATE_LABEL[state]}
        </span>
      </div>

      {/* ⚠️ 여기 둘은 **오류가 아닙니다.** 정보 부족은 대화의 한 단계이고(기획서 9.3),
          열화는 설계된 동작입니다(ADR-0005). 오류 화면으로 보내면 사용자는 자기가 뭘
          잘못했다고 읽습니다. 둘을 가르는 근거는 `needsInput` 키의 유무입니다. */}
      {needsInput !== undefined && (
        <p className="notice notice-input">
          {needsInput.reason} (요구 항목: {needsInput.field})
        </p>
      )}
      {messageMode === "degraded" && (
        <p className="notice notice-degraded">
          자동 채움을 건너뛰고 입력한 내용으로만 진행합니다. 카테고리와 타겟이 비어 있습니다.
        </p>
      )}

      {state === "brief_filling" && (
        <div className="empty-state">
          <strong>브리프를 더 채워야 시안을 만들 수 있습니다</strong>
          {/* 여기서 막히는 것이 지금의 한계입니다. 브리프 수정 화면(F5, 06 일정 08-21)이
              붙기 전까지는 새 세션을 만드는 것이 유일한 길이며, 그 사실을 숨기지 않습니다. */}
          <p>브리프 수정 화면이 아직 없습니다. 정보를 보완해 새 세션으로 다시 시작해 주세요.</p>
        </div>
      )}

      {state === "brief_ready" &&
        (session.outputType === "comic" ? (
          // ⚠️ 관통 경로는 **단일 광고형 하나**입니다 (구현_범위 1절). 만화형은 분기 지점만
          // 두고 스텁이며, 지금 시안 생성을 부르면 엔진이 503 으로 거절합니다 - 그리고 그
          // 503 은 화면에 "엔진에 연결하지 못했습니다"로 도착합니다. 없는 장애를 있다고
          // 말하는 것이라, 부를 수 없는 이유를 여기서 먼저 말하고 버튼을 내립니다.
          <p className="notice notice-degraded">
            만화형은 아직 시안 생성이 열려 있지 않습니다. 분기만 만들어 둔 상태이며(구현_범위
            1절), 지금 관통하는 것은 단일 광고형입니다.
          </p>
        ) : (
          <div className="stage-action">
            {/* 되돌릴 수 없는 마지막 지점이라는 사실을 화면이 말해야 합니다 (INV-7). */}
            <p className="contract-note">
              시안을 만들면 브리프가 잠깁니다. 생성에 실패하면 잠금은 다시 풀립니다.
            </p>
            <button
              className="submit-button"
              type="button"
              onClick={onGenerate}
              disabled={pending !== null}
            >
              {pending === "draft" ? "시안을 만드는 중..." : "시안 만들기"}
            </button>
          </div>
        ))}

      {state === "draft_generating" && (
        <div className="empty-state" aria-live="polite">
          <strong>시안을 만들고 있습니다</strong>
          <p>다른 탭에서 시작한 생성일 수 있습니다. 잠시 후 다시 불러와 주세요.</p>
          <button type="button" className="link-button" onClick={onReload}>
            다시 불러오기
          </button>
        </div>
      )}

      {draft !== undefined && <DraftView draft={draft} />}

      {state === "draft_ready" && (
        <div className="stage-action">
          {/* 확정은 세션당 1회이고, 그것이 비용 방어선입니다 (INV-3). 되돌릴 수 없다는
              사실을 누르기 전에 알려 줍니다 - 누른 뒤에 알리면 알림이 아니라 통보입니다. */}
          <p className="contract-note">
            확정하면 이미지 생성이 시작되고 시안은 더 이상 고칠 수 없습니다. 세션당 한 번입니다.
          </p>
          <button
            className="submit-button"
            type="button"
            onClick={onFinalize}
            disabled={pending !== null}
          >
            {pending === "finalize" ? "확정하는 중..." : "확정하고 이미지 만들기"}
          </button>
        </div>
      )}

      {session.jobId !== undefined &&
        (job === null ? (
          <p className="notice">렌더 상태를 확인하고 있습니다...</p>
        ) : (
          <ResultView job={job} productName={session.brief.productName} />
        ))}

      {state === "failed" && (
        <p className="notice notice-failed">
          이 세션은 실패로 끝났습니다. 되돌리는 경로가 없으므로 새 세션으로 다시 시작해 주세요.
        </p>
      )}
    </section>
  );
}

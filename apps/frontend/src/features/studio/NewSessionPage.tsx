import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createSession } from "./api";
import { BriefForm } from "./components/BriefForm";
import { useApiError } from "./errors";
import type { SessionCreateInput } from "./types";

const STEPS = [
  "입력한 정보로 브리프를 채웁니다",
  "브리프를 확인하고 시안을 만듭니다",
  "시안을 확정하면 이미지 생성이 시작됩니다",
  "완성된 이미지를 내려받습니다",
];

export function NewSessionPage() {
  const navigate = useNavigate();
  const { message, report, clear } = useApiError();
  const [pending, setPending] = useState(false);

  const create = async (input: SessionCreateInput) => {
    clear();
    setPending(true);
    try {
      const session = await createSession(input);
      // 세션이 생긴 순간부터 진행 상태의 주인은 URL 입니다. 그래야 새로고침해도, 링크를
      // 다시 열어도 같은 세션으로 돌아옵니다.
      void navigate(`/sessions/${session.sessionId}`);
    } catch (error: unknown) {
      report(error);
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <header className="workspace-header">
        <div>
          <p className="eyebrow">AI CREATIVE STUDIO</p>
          <h1>어떤 광고를 만들어볼까요?</h1>
        </div>
      </header>

      {message !== null && (
        <p className="workspace-error" role="alert">
          {message}
        </p>
      )}

      <div className="workspace-grid">
        <BriefForm onSubmit={(input) => void create(input)} pending={pending} />

        <section className="panel draft-panel" aria-labelledby="guide-heading">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">STEP 02</p>
              <h2 id="guide-heading">브리프 · 시안 · 결과</h2>
            </div>
            <span className="status-chip">입력 대기</span>
          </div>

          <div className="empty-state">
            <div className="empty-blocks" aria-hidden="true"><i /><i /><i /></div>
            <strong>왼쪽 정보를 제출하면 여기서 이어집니다</strong>
            <ol className="step-list">
              {STEPS.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        </section>
      </div>
    </>
  );
}

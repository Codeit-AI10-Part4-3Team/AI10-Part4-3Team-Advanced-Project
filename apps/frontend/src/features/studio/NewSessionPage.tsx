import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createSession } from "./api";
import { BriefForm } from "./components/BriefForm";
import { useApiError } from "./errors";
import { ErrorNotice } from "./components/ErrorNotice";
import type { SessionCreateInput } from "./types";

const STEPS = [
  "입력한 정보로 브리프를 채웁니다",
  "브리프를 확인하고 시안을 만듭니다",
  "시안을 확정하면 이미지 생성이 시작됩니다",
  "완성된 이미지를 내려받습니다",
];

export function NewSessionPage() {
  const navigate = useNavigate();
  const { failure, report, clear } = useApiError();
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
    // ⚠️ 이 클래스가 폭을 정합니다. 세 패널이 화면을 채우도록 여기서만 `max-width` 를 풀고,
    // 좌우 여백도 좁힙니다 (styles.css 의 `.workspace:has(.new-session)`).
    <div className="new-session">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">AI CREATIVE STUDIO</p>
          <h1>어떤 광고를 만들어볼까요?</h1>
        </div>
      </header>

      {failure !== null && <ErrorNotice failure={failure} onDismiss={clear} />}

      {/* 격자는 `BriefForm` 이 그립니다 - 세 패널이 한 `<form>` 에 속해야 화풍 라디오가
          제출에 함께 실립니다. 여기서는 세 번째 칸의 내용만 넘깁니다. */}
      <BriefForm
        onSubmit={(input) => void create(input)}
        pending={pending}
        guide={
          <section className="panel draft-panel" aria-labelledby="guide-heading">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">STEP 03</p>
                <h2 id="guide-heading">브리프, 시안, 결과</h2>
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
        }
      />
    </div>
  );
}

import type { BriefInput } from "../types";

interface DraftPanelProps {
  brief: BriefInput | null;
}

export function DraftPanel({ brief }: DraftPanelProps) {
  return (
    <section className="panel draft-panel" aria-labelledby="draft-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">STEP 02</p>
          <h2 id="draft-heading">브리프 · 시안 · 결과</h2>
        </div>
        <span className={`status-chip ${brief ? "ready" : ""}`}>
          {brief ? "입력 확인" : "입력 대기"}
        </span>
      </div>

      {!brief ? (
        <div className="empty-state" aria-live="polite">
          <div className="empty-blocks" aria-hidden="true"><i /><i /><i /></div>
          <strong>광고 정보가 여기에 정리됩니다</strong>
          <p>왼쪽 폼을 제출하면 브리프 확인 화면의 구조를 미리 볼 수 있습니다.</p>
        </div>
      ) : (
        <div className="brief-preview" aria-live="polite">
          <div className="preview-title">
            <div>
              <span>제품명</span>
              <h3>{brief.productName}</h3>
            </div>
            <button type="button">수정</button>
          </div>
          <dl>
            <div><dt>출력 유형</dt><dd>{brief.outputType === "comic" ? "6컷 광고 만화" : "단일 광고"}</dd></div>
            <div><dt>제품 이미지</dt><dd>{brief.productImageName}</dd></div>
            <div className="wide"><dt>핵심 소구점</dt><dd>{brief.sellingPoint}</dd></div>
            <div><dt>화풍</dt><dd>{brief.artStyle || "무작위 추천"}</dd></div>
            <div><dt>추가 메모</dt><dd>{brief.note || "없음"}</dd></div>
          </dl>
          {brief.outputType === "comic" && (
            <div className="contract-note">만화형은 계약에 따라 정확히 6컷으로 생성됩니다.</div>
          )}
          <button className="submit-button" type="button" disabled>API 연결 후 시안 생성</button>
        </div>
      )}

      <div className="result-section">
        <div className="result-heading">
          <h3>최종 렌더 결과</h3>
          <button type="button" disabled>이미지 저장</button>
        </div>
        <div className="result-placeholder">
          <span>queued</span><span>running</span><span>done</span><span>failed</span>
        </div>
      </div>
    </section>
  );
}

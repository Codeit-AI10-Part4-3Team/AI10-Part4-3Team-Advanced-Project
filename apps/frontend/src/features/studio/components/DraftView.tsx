import { PANEL_ROLE_LABEL } from "../labels";
import { isComicDraft, type Draft } from "../types";

/**
 * 시안 본문. **텍스트만 있습니다** - 시안 단계에는 그림이 없고, 이미지 경로나 미리보기가
 * 여기 들어오는 순간 "확정 전에는 그림을 만들지 않는다"가 깨집니다.
 *
 * `adPlan` 은 읽기 전용입니다 (INV-8). 브리프와 내용이 겹쳐 따로 고칠 수 있게 두면 둘이
 * 서로 다른 말을 하는 시안이 만들어집니다.
 */
export function DraftView({ draft }: { draft: Draft }) {
  return (
    <div className="draft-view">
      <div className="ad-plan">
        <h3>광고 기획안</h3>
        <p>{draft.adPlan}</p>
      </div>

      {isComicDraft(draft) ? (
        <ol className="panel-grid">
          {draft.panels.map((panel) => (
            <li key={panel.index}>
              <span className="panel-role">
                {panel.index}. {PANEL_ROLE_LABEL[panel.role]}
              </span>
              <p className="panel-scene">{panel.scene}</p>
              <p className="panel-dialogue">{panel.dialogue}</p>
            </li>
          ))}
        </ol>
      ) : (
        <dl className="single-ad">
          <div>
            <dt>카피</dt>
            <dd>{draft.copy}</dd>
          </div>
          <div>
            <dt>비주얼 구성</dt>
            <dd>{draft.visualPlan}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}

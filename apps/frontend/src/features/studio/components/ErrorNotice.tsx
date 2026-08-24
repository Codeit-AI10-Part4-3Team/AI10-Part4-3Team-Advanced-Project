import type { Described } from "../errors";

interface ErrorNoticeProps {
  failure: Described;
  onDismiss: () => void;
  /** 폴링이 멈춘 것처럼 되살릴 길이 있을 때만 넣습니다. */
  retry?: { label: string; onClick: () => void };
}

/**
 * 실패를 화면 **우측 상단 고정 영역**에 띄웁니다 (기획서 12.5).
 *
 * ⚠️ **흐름을 막지 않습니다.** 같은 절이 팝업을 명시적으로 반려했습니다 - 모달은 화면 상태
 * 관리와 흐름 차단 처리가 함께 필요한데, "개발 단계에서 무엇 때문에 실패했는지 즉시 확인"
 * 이라는 목적에는 과한 수단이라는 이유입니다. 그래서 겹쳐 놓되 뒤를 계속 쓸 수 있습니다.
 *
 * ⚠️ **딱지(`label`)가 5 종을 가릅니다.** 문구를 다 읽어야 어느 실패인지 알 수 있으면 구분이
 * 되지 않습니다. 5 종이 아닌 코드에는 딱지가 없고, 그 없음 자체가 "실패가 아니라 상태가
 * 어긋난 것" 이라는 표시입니다.
 *
 * ⚠️ **코드를 함께 보여 줍니다.** 기획서 12.5 의 개발 단계 목적이 "어느 단계에서 무엇 때문에"
 * 를 즉시 아는 것입니다. 사용자용 문구는 배포 단계에서 따로 정하기로 되어 있어(같은 절, 17 절)
 * 지금은 이 표기가 남습니다.
 */
export function ErrorNotice({ failure, onDismiss, retry }: ErrorNoticeProps) {
  return (
    // `alert` 는 스크린 리더가 즉시 읽습니다. 실패는 사용자가 찾아가는 것이 아니라 알려야
    // 하는 것이라 `status` 가 아니라 이쪽입니다.
    <div className="error-notice" role="alert">
      <div className="error-notice-head">
        {failure.label !== undefined && <span className="error-notice-tag">{failure.label}</span>}
        {failure.code !== undefined && <code>{failure.code}</code>}
        <button type="button" className="error-notice-close" aria-label="오류 닫기" onClick={onDismiss}>
          <span aria-hidden="true">x</span>
        </button>
      </div>
      <p>{failure.message}</p>
      {retry !== undefined && (
        <button type="button" className="link-button" onClick={retry.onClick}>
          {retry.label}
        </button>
      )}
    </div>
  );
}

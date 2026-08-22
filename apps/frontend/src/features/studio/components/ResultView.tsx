import { describeCode } from "../errors";
import { JOB_STATUS_LABEL } from "../labels";
import type { ApiErrorBody, Job } from "../types";

interface ResultViewProps {
  job: Job;
  productName: string;
}

function expiryText(expiresAt: string): string {
  const at = new Date(expiresAt);
  return Number.isNaN(at.getTime()) ? expiresAt : at.toLocaleString("ko-KR");
}

/**
 * 렌더 잡의 현재 모습.
 *
 * ⚠️ **키의 유무로 분기합니다.** `result` 와 `error` 는 해당 상황에서만 실리고 계약에
 * `null` 이 없으므로, `status` 로 갈라 놓고 값을 비교하지 않습니다.
 */
/** 잡이 남긴 실패. `error` 키가 없을 수도 있어(계약) 그때는 최소한만 말합니다. */
function JobFailure({ error }: { error?: ApiErrorBody }) {
  if (error === undefined) {
    return (
      <p className="workspace-error" role="alert">
        이미지 생성에 실패했습니다.
      </p>
    );
  }
  const described = describeCode(error.code, error.message);
  return (
    <p className="workspace-error" role="alert">
      {described.label !== undefined && <strong>{described.label}</strong>}
      {described.label !== undefined && " "}
      {described.message}
    </p>
  );
}

export function ResultView({ job, productName }: ResultViewProps) {
  return (
    <div className="result-section">
      <div className="result-heading">
        <h3>최종 렌더 결과</h3>
        <span className={`status-chip ${job.status === "done" ? "ready" : ""}`}>
          {JOB_STATUS_LABEL[job.status]}
        </span>
      </div>

      {(job.status === "queued" || job.status === "running") && (
        <div className="empty-state" aria-live="polite">
          <div className="empty-blocks" aria-hidden="true"><i /><i /><i /></div>
          {/* 진행률을 만들지 않습니다. 외부 생성 API 는 남은 시간을 알려 주지 않으므로,
              여기서 그리는 진행률은 전부 지어낸 값입니다. */}
          <strong>이미지를 만들고 있습니다</strong>
          <p>
            {job.queuePosition === undefined
              ? "완료되면 이 화면이 자동으로 바뀝니다. 창을 닫아도 다시 열면 이어집니다."
              : `대기 순서 ${job.queuePosition}번입니다. GPU 한 대로 한 건씩 처리합니다.`}
          </p>
        </div>
      )}

      {/* ⚠️ 잡 실패는 **여기 남습니다.** 우측 상단 알림은 지나가는 통지이고, 이것은 세션이
          끝난 상태라 결과 자리에 그대로 있어야 합니다. 5 종 딱지는 같은 표에서 나오므로
          어느 실패인지는 두 곳에서 같게 읽힙니다. */}
      {job.status === "failed" && <JobFailure error={job.error} />}

      {job.status === "done" && job.result !== undefined && (
        <div className="result-done">
          <img
            className="result-image"
            src={job.result.imageUrl}
            width={job.result.width}
            height={job.result.height}
            alt={`${productName} 광고 결과 이미지`}
          />
          <div className="result-actions">
            {/* ⚠️ `download` 는 **같은 출처일 때만** 동작합니다. `VITE_API_BASE_URL` 에
                절대 URL 을 넣으면 브라우저가 이 속성을 무시하고 이미지를 새 탭에서 열기만
                합니다 - 세션 쿠키도 그때 함께 문제가 되므로, 같은 출처가 기본값인 이유가
                여기에도 걸립니다 (client.ts). */}
            <a className="submit-button" href={job.result.imageUrl} download={`${productName}.webp`}>
              이미지 저장
            </a>
            {/* 만료를 404 로 알게 하지 않습니다. 계약이 `expiresAt` 을 미리 주는 이유가
                이것이고, 화면은 사용자가 내려받을 시간이 남아 있을 때 그 사실을 말합니다. */}
            <small>{expiryText(job.result.expiresAt)}까지 내려받을 수 있습니다.</small>
          </div>
        </div>
      )}
    </div>
  );
}

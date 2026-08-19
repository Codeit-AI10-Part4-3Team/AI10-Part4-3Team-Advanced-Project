import { OUTPUT_TYPE_LABEL } from "../labels";
import type { FieldMeta, Session } from "../types";

interface BriefSummaryProps {
  session: Session;
}

/**
 * 서버가 채운 값에만 표시를 답니다.
 *
 * ⚠️ 사용자가 직접 쓴 값(`user`)에는 아무 표시도 하지 않습니다 - 전부에 딱지를 붙이면
 * 아무것도 구분되지 않습니다. **고치는 것은 아직 안 됩니다**(F5, 06 일정 08-21). 표시만
 * 먼저 두는 이유는, 자동으로 채워진 값을 사용자가 자기가 쓴 것으로 오해한 채 시안까지
 * 넘어가면 그 시점에는 브리프가 잠겨 되돌릴 수 없기 때문입니다 (INV-7).
 */
function FilledMark({ meta }: { meta?: FieldMeta }) {
  if (meta === undefined || meta.filledBy === "user") return null;
  const label = meta.filledBy === "inferred" ? "자동 추론" : "자동 지정";
  return <em className="filled-mark">{label}</em>;
}

export function BriefSummary({ session }: BriefSummaryProps) {
  const { brief, briefMeta, outputType } = session;

  return (
    <section className="panel brief-panel" aria-labelledby="brief-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">STEP 01</p>
          <h2 id="brief-heading">광고 브리프</h2>
        </div>
        <span>{OUTPUT_TYPE_LABEL[outputType]}</span>
      </div>

      {/* ⚠️ 사진이 만료되면 `productImageUrl` 이 빈 문자열입니다 (보존 24시간, 세션은 7일).
          그때 `<img>` 를 그리면 404 를 받아 깨진 이미지가 남으므로, 값이 비었는지로 먼저
          분기합니다 - 만료를 응답이 아니라 이 필드로 알라는 것이 계약의 규칙입니다. */}
      {brief.productImageUrl === "" ? (
        <p className="image-expired">업로드한 사진의 보관 기간(24시간)이 지났습니다.</p>
      ) : (
        <img className="product-image" src={brief.productImageUrl} alt="업로드한 제품 사진" />
      )}

      <dl className="brief-fields">
        <div>
          <dt>제품명 <FilledMark meta={briefMeta.productName} /></dt>
          <dd>{brief.productName}</dd>
        </div>
        <div>
          <dt>화풍 <FilledMark meta={briefMeta.artStyle} /></dt>
          <dd>{brief.artStyle || "미지정"}</dd>
        </div>
        <div className="wide">
          <dt>핵심 소구점 <FilledMark meta={briefMeta.sellingPoint} /></dt>
          <dd>{brief.sellingPoint}</dd>
        </div>
        <div>
          <dt>카테고리 <FilledMark meta={briefMeta.category} /></dt>
          <dd>{brief.category || "미정"}</dd>
        </div>
        <div>
          <dt>타겟 <FilledMark meta={briefMeta.target} /></dt>
          <dd>{brief.target || "미정"}</dd>
        </div>
        {brief.aspectRatio !== undefined && (
          <div>
            <dt>비율 <FilledMark meta={briefMeta.aspectRatio} /></dt>
            <dd>{brief.aspectRatio}</dd>
          </div>
        )}
        {brief.character !== undefined && (
          <div className="wide">
            <dt>캐릭터 <FilledMark meta={briefMeta.character} /></dt>
            <dd>{`${brief.character.appearance} / ${brief.character.outfit}`}</dd>
          </div>
        )}
        <div className="wide">
          <dt>추가 메모 <FilledMark meta={briefMeta.note} /></dt>
          <dd>{brief.note || "없음"}</dd>
        </div>
      </dl>
    </section>
  );
}

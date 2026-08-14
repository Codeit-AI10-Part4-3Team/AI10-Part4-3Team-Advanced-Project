import { useState, type FormEvent } from "react";
import type { BriefInput, OutputType } from "../types";

interface BriefFormProps {
  onPreview: (brief: BriefInput) => void;
}

const initialBrief: BriefInput = {
  outputType: "single_ad",
  productName: "",
  sellingPoint: "",
  note: "",
  artStyle: "",
  productImageName: "",
};

export function BriefForm({ onPreview }: BriefFormProps) {
  const [brief, setBrief] = useState(initialBrief);

  const update = <K extends keyof BriefInput>(key: K, value: BriefInput[K]) => {
    setBrief((current) => ({ ...current, [key]: value }));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onPreview(brief);
  };

  return (
    <section className="panel brief-panel" aria-labelledby="brief-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">STEP 01</p>
          <h2 id="brief-heading">광고 정보 입력</h2>
        </div>
        <span>* 필수 항목</span>
      </div>

      <form onSubmit={submit}>
        <div className="type-tabs" role="tablist" aria-label="출력 유형">
          {(["single_ad", "comic"] as OutputType[]).map((type) => (
            <button
              key={type}
              type="button"
              role="tab"
              aria-selected={brief.outputType === type}
              className={brief.outputType === type ? "active" : ""}
              onClick={() => update("outputType", type)}
            >
              {type === "single_ad" ? "단일 광고" : "6컷 광고 만화"}
            </button>
          ))}
        </div>

        <label className="field">
          <span>제품 이미지 *</span>
          <input
            className="file-input"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            required
            onChange={(event) => update("productImageName", event.target.files?.[0]?.name ?? "")}
          />
          <small>JPEG, PNG, WebP · 최대 10MB · 짧은 변 512px 이상</small>
        </label>

        <label className="field">
          <span>제품명 *</span>
          <input
            value={brief.productName}
            maxLength={40}
            required
            placeholder="예: 행복 블렌드 커피"
            onChange={(event) => update("productName", event.target.value)}
          />
        </label>

        <label className="field">
          <span>핵심 소구점 *</span>
          <textarea
            value={brief.sellingPoint}
            maxLength={200}
            required
            rows={3}
            placeholder="광고가 근거로 사용할 제품의 실제 특징을 적어주세요."
            onChange={(event) => update("sellingPoint", event.target.value)}
          />
          <small>{brief.sellingPoint.length}/200</small>
        </label>

        <label className="field">
          <span>화풍</span>
          <select value={brief.artStyle} onChange={(event) => update("artStyle", event.target.value)}>
            <option value="">무작위 추천</option>
            <option value="minimal">미니멀</option>
            <option value="warm-daily">따뜻한 일상</option>
            <option value="bold-pop">선명한 팝</option>
          </select>
          <small>실제 목록은 `GET /v1/art-styles` 응답으로 교체합니다.</small>
        </label>

        <label className="field">
          <span>추가 메모</span>
          <textarea
            value={brief.note}
            maxLength={500}
            rows={3}
            placeholder="캐릭터, 금지 표현, 꼭 포함할 문구 등을 적어주세요."
            onChange={(event) => update("note", event.target.value)}
          />
        </label>

        <button className="submit-button" type="submit">브리프 확인하기</button>
      </form>
    </section>
  );
}

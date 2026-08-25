import { useEffect, useState, type FormEvent } from "react";
import { listArtStyles } from "../api";
import { ArtStylePicker } from "./ArtStylePicker";
import { OUTPUT_TYPE_LABEL } from "../labels";
import type { ArtStyle, OutputType, SessionCreateInput } from "../types";

interface BriefFormProps {
  onSubmit: (input: SessionCreateInput) => void;
  pending: boolean;
}

/** 계약의 `SessionCreateRequest.productImage` 가 정한 상한입니다. */
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

type TextFields = Omit<SessionCreateInput, "productImage">;

const INITIAL: TextFields = {
  outputType: "single_ad",
  productName: "",
  sellingPoint: "",
  note: "",
  artStyle: "",
};

export function BriefForm({ onSubmit, pending }: BriefFormProps) {
  const [fields, setFields] = useState<TextFields>(INITIAL);
  const [image, setImage] = useState<File | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [artStyles, setArtStyles] = useState<ArtStyle[]>([]);

  // ⚠️ **후보를 화면에 지어내지 않습니다.** 값이 들어오는 통로는 `ADGEN_ART_STYLES` 설정
  // 하나이고(AGENTS.md), 여기에 손으로 적은 값은 그대로 브리프에 실려 세션에 저장되므로
  // 나중에 어느 세션이 무엇으로 생성됐는지 알 수 없게 됩니다.
  //
  // 목록 자체는 확정됐습니다 - A-3 는 2026-08-24 회의 안건 01 이 닫았고 05 가 08-22 에
  // 값 8종을 배포했습니다. 그래도 **비어 있는 응답은 여전히 정상 경로입니다**: 설정이 아직
  // 안 들어간 환경(새 로컬 스택, 새 배포)이 그렇고, 그때는 미선택으로 보내 서버가 채웁니다.
  useEffect(() => {
    let cancelled = false;

    listArtStyles()
      .then((next) => {
        if (!cancelled) setArtStyles(next);
      })
      .catch((error: unknown) => {
        // 화풍은 선택 항목입니다. 목록을 못 읽었다고 입력 자체를 막으면 필수도 아닌 것이
        // 관통을 세웁니다.
        if (!cancelled) console.warn("화풍 목록을 불러오지 못했습니다.", error);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const update = <K extends keyof TextFields>(key: K, value: TextFields[K]) => {
    setFields((current) => ({ ...current, [key]: value }));
  };

  const pickImage = (file: File | undefined) => {
    setImage(file ?? null);
    // 크기만 먼저 봅니다. 형식과 짧은 변 512px 은 서버가 판정하며(422 `INVALID_IMAGE`),
    // 여기서 다시 구현하면 두 판정이 어긋날 때 어느 쪽이 맞는지 정할 근거가 없습니다.
    // 크기를 예외로 둔 이유는 10MB 를 올려 보내고 나서 거절당하는 왕복이 아깝기 때문입니다.
    setImageError(
      file !== undefined && file.size > MAX_IMAGE_BYTES ? "이미지가 10MB 를 넘습니다." : null,
    );
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (image === null || imageError !== null) return;
    onSubmit({ ...fields, productImage: image });
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
              aria-selected={fields.outputType === type}
              className={fields.outputType === type ? "active" : ""}
              onClick={() => update("outputType", type)}
            >
              {OUTPUT_TYPE_LABEL[type]}
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
            onChange={(event) => pickImage(event.target.files?.[0])}
          />
          <small>JPEG, PNG, WebP · 최대 10MB · 짧은 변 512px 이상</small>
        </label>
        {imageError !== null && <p className="form-error">{imageError}</p>}

        <label className="field">
          <span>제품명 *</span>
          <input
            value={fields.productName}
            maxLength={40}
            required
            placeholder="예: 행복 블렌드 커피"
            onChange={(event) => update("productName", event.target.value)}
          />
        </label>

        <label className="field">
          <span>핵심 소구점 *</span>
          <textarea
            value={fields.sellingPoint}
            maxLength={200}
            required
            rows={3}
            placeholder="광고가 근거로 사용할 제품의 실제 특징을 적어주세요."
            onChange={(event) => update("sellingPoint", event.target.value)}
          />
          {/* 여기 적은 것이 가드레일의 **근거 원문**입니다. 없는 효능과 수치는 생성물에
              등장할 수 없으므로, 비어 있을수록 시안이 거절될 확률이 올라갑니다. */}
          <small>{fields.sellingPoint.length}/200</small>
        </label>

        <div className="field">
          <span>화풍</span>
          <ArtStylePicker
            styles={artStyles}
            value={fields.artStyle}
            onChange={(id) => update("artStyle", id)}
          />
        </div>

        <label className="field">
          <span>추가 메모</span>
          <textarea
            value={fields.note}
            maxLength={500}
            rows={3}
            placeholder="캐릭터, 금지 표현, 꼭 포함할 문구 등을 적어주세요."
            onChange={(event) => update("note", event.target.value)}
          />
        </label>

        <button className="submit-button" type="submit" disabled={pending || imageError !== null}>
          {pending ? "세션을 만드는 중..." : "광고 만들기 시작"}
        </button>
      </form>
    </section>
  );
}

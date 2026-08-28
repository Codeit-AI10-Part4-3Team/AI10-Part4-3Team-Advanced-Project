import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { listArtStyles } from "../api";
import { ArtStylePicker } from "./ArtStylePicker";
import { OUTPUT_TYPE_LABEL } from "../labels";
import type { ArtStyle, OutputType, SessionCreateInput } from "../types";

interface BriefFormProps {
  onSubmit: (input: SessionCreateInput) => void;
  pending: boolean;
  /**
   * 세 번째 패널(STEP 03). 폼이 그리지 않고 받아서 격자에 놓기만 합니다.
   *
   * ⚠️ 폼 **안**에 들어갑니다. 세 패널이 한 격자를 이루려면 격자의 자식이어야 하고, 격자가
   * 곧 `<form>` 이기 때문입니다. 그 안에 제출 버튼을 두지 마세요 - 이 폼이 제출됩니다.
   */
  guide: ReactNode;
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

export function BriefForm({ onSubmit, pending, guide }: BriefFormProps) {
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

  /**
   * 필수 넷이 다 찼는가. 버튼의 활성 조건입니다.
   *
   * ⚠️ **계약의 `required` 와 같은 목록입니다** (openapi.yaml 의 `SessionCreateRequest`):
   * `outputType`, `productImage`, `productName`, `sellingPoint`. `outputType` 은 기본값이
   * 있어 비는 경우가 없으므로 여기서 세지 않습니다.
   *
   * ⚠️ 공백만 친 것은 채운 것이 아닙니다. 계약이 `minLength: 1` 이라 서버는 공백 하나도
   * 받지만, 그렇게 만든 세션은 가드레일의 근거가 비어 시안이 거절됩니다.
   */
  /**
   * 아직 비어 있는 필수 칸.
   *
   * ⚠️ **버튼을 잠그면 브라우저의 `required` 안내가 도달하지 못합니다.** 예전에는 눌렀을 때
   * 브라우저가 "이 입력란을 작성하세요" 를 빈 칸 위에 띄웠는데, 비활성 버튼은 클릭도 암묵적
   * 제출(Enter)도 아무 일을 하지 않습니다. 필수가 셋이라 이름을 대 주지 않으면 사용자가
   * 스스로 찾아야 합니다 (PR #266 리뷰, 신호정).
   */
  const missing = [
    image === null ? "제품 이미지" : null,
    fields.productName.trim() === "" ? "제품명" : null,
    fields.sellingPoint.trim() === "" ? "제품 특징" : null,
  ].filter((name): name is string => name !== null);

  const ready = missing.length === 0 && imageError === null;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (image === null || !ready) return;
    onSubmit({ ...fields, productImage: image });
  };

  return (
    // ⚠️ **`<form>` 이 격자 자체입니다.** 세 패널이 같은 폼에 속해야 화풍 라디오가 제출에
    // 함께 실리고, Enter 키와 필수 검사도 한 덩어리로 동작합니다. 패널마다 폼을 따로 두면
    // 화풍이 다른 폼에 갇혀 제출에서 빠집니다.
    <form className="workspace-grid workspace-grid-3" onSubmit={submit}>
      <section className="panel brief-panel" aria-labelledby="brief-heading">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">STEP 01</p>
            <h2 id="brief-heading">광고 정보 입력</h2>
          </div>
        </div>

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
          {/* ⚠️ 별표 하나로는 필수라는 것이 전달되지 않습니다. 글자로 적고 색을 줍니다 -
              색만으로 가르면 색을 구분하지 못하는 사용자에게는 표시가 없는 것과 같습니다. */}
          <span>
            제품 이미지 <em className="required">(필수)</em>
          </span>
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
          <span>
            제품명 <em className="required">(필수)</em>
          </span>
          <input
            value={fields.productName}
            maxLength={40}
            required
            placeholder="예: 행복 블렌드 커피"
            onChange={(event) => update("productName", event.target.value)}
          />
        </label>

        <label className="field">
          {/* ⚠️ 계약의 필드 이름은 `sellingPoint` 그대로입니다. 바꾼 것은 **화면 문구**뿐이고,
              "소구점" 이 업계 용어라 처음 쓰는 사람이 무엇을 적어야 할지 모릅니다.

              ⚠️ **"장점" 이 아니라 "특징" 입니다** (2026-08-28, PR #302 리뷰에서 01 이 정했습니다).
              이 칸은 자랑거리를 적는 자리가 아니라 **생성물이 넘을 수 없는 울타리**입니다 -
              계약이 `sellingPoint` 를 "가드레일의 근거 원문. 여기에 없는 수치와 효능은 생성물에
              등장할 수 없습니다" 로 정의합니다(`openapi.yaml`). "장점" 은 "좋은 점만 적어야
              하나" 로 읽혀 근거가 좁아집니다.

              ⚠️ **아래 안내 문구와 같은 말을 써야 합니다.** 한동안 라벨만 "장점" 이고 안내와
              placeholder 는 "특징" 쪽이었습니다. 어긋나면 사용자가 무엇을 적을지 두 번
              판단하게 됩니다. 시험이 둘의 일치를 겁니다. */}
          <span>
            제품 특징 <em className="required">(필수)</em>
          </span>
          <textarea
            value={fields.sellingPoint}
            maxLength={200}
            required
            rows={3}
            placeholder="예: 무향 무알코올, 두꺼운 원단"
            onChange={(event) => update("sellingPoint", event.target.value)}
          />
          {/* 여기 적은 것이 가드레일의 **근거 원문**입니다. 없는 효능과 수치는 생성물에
              등장할 수 없으므로, 비어 있을수록 시안이 거절될 확률이 올라갑니다. */}
          <small>광고가 근거로 쓸 제품의 실제 특징을 적어주세요.</small>
          <small>{fields.sellingPoint.length}/200</small>
        </label>

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

        {/* ⚠️ 필수를 다 채우기 전에는 누를 수 없습니다. `required` 속성은 남겨 두었지만
            **그 검사는 이제 도달하지 않습니다** - `ready` 가 거짓인 조건이 세 칸이 빈 조건의
            상집합이라, 폼이 제출되는데 그 칸이 비어 있는 상태가 존재하지 않습니다. 그래서
            어느 칸이 비었는지는 아래 문구가 직접 말합니다. */}
        <button className="submit-button" type="submit" disabled={pending || !ready}>
          {pending ? "세션을 만드는 중..." : "광고 만들기 시작"}
        </button>
        {!ready && !pending && (
          // ⚠️ **`role="status"` 가 이 문구의 전부입니다.** 비활성 버튼은 탭 순서에서
          //    건너뛰므로, 화면을 못 보는 사용자는 여기까지 오지 못하고 문구가 바뀌어도
          //    알림이 없습니다. 그러면 칸을 채워 나가도 무엇이 남았는지 계속 모릅니다.
          //    바뀌는 횟수는 필수 셋이 채워지는 동안 최대 세 번이라 시끄럽지 않습니다
          //    (PR #266 리뷰, 신호정). 같은 규약을 `BriefSummary` 와 `ResultView` 가 씁니다.
          <p className="submit-hint" role="status">
            {missing.length > 0
              ? `아직 비어 있습니다: ${missing.join(", ")}`
              : "이미지를 다시 골라 주세요."}
          </p>
        )}
      </section>

      <section className="panel style-panel" aria-labelledby="style-heading">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">STEP 02</p>
            <h2 id="style-heading">화풍 선택</h2>
          </div>
        </div>
        <ArtStylePicker
          styles={artStyles}
          value={fields.artStyle}
          onChange={(id) => update("artStyle", id)}
        />
      </section>

      {guide}
    </form>
  );
}

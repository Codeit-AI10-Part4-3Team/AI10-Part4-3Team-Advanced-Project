import { useEffect, useId, useRef, useState } from "react";
import type { ArtStyle } from "../types";

interface ArtStylePickerProps {
  styles: ArtStyle[];
  /** 빈 문자열은 **미선택**입니다. 그때 서버가 후보군에서 무작위로 채웁니다. */
  value: string;
  onChange: (artStyleId: string) => void;
}

/**
 * 화풍 후보를 한 화면에 격자로 놓고 고릅니다.
 *
 * ⚠️ **드롭다운이 아니라 격자인 이유는 비교입니다.** 화풍은 말로 전달되지 않아 예시 이미지를
 * 함께 보여주기로 되어 있고(2026-08-11 회의), 하나씩 열어 보는 방식으로는 후보끼리 견줄 수가
 * 없습니다. 4 x 2 는 기획서 12.2 의 화면 도식이며 **후보가 8 종인 근거도 그 격자**입니다.
 *
 * ⚠️ **후보를 화면이 지어내지 않습니다.** 목록은 `GET /v1/art-styles` 에서만 오고, 카드에
 * 적을 수 있는 것은 계약의 `ArtStyle` 이 주는 `name` 과 `exampleImageUrl` 뿐입니다. 특징
 * 설명(굵은 선, 단순한 색 ...)은 계약에 없어 여기 적으면 지어낸 값이 됩니다
 * (apps/frontend/AGENTS.md).
 *
 * ⚠️ **예시 이미지가 아직 없습니다.** `exampleImageUrl` 이 빈 문자열이면 자리만 잡고 "예시
 * 준비 중"을 보여줍니다. 아무 그림이나 채우면 안 되는 이유가 따로 있습니다 - 예시와 실제
 * 결과의 화풍이 같은 프롬프트 조각에서 나와야 하고, 그렇지 않으면 선택 화면 전체가 거짓말이
 * 됩니다 (03-AI_생성_서빙.md).
 */
export function ArtStylePicker({ styles, value, onChange }: ArtStylePickerProps) {
  // 같은 화면에 픽커가 둘 이상 있어도 라디오 그룹이 섞이지 않게 합니다.
  const groupName = useId();
  const [zoomed, setZoomed] = useState<ArtStyle | null>(null);

  if (styles.length === 0) {
    // 후보가 비어 있는 것은 지금 정상입니다 (`ADGEN_ART_STYLES` 미설정). 빈 격자를 그리면
    // 고장으로 읽히므로 이유를 말하고 격자를 내립니다.
    return (
      <p className="art-style-empty">
        화풍 후보가 아직 설정에 들어오지 않았습니다. 서버가 무작위로 채웁니다.
      </p>
    );
  }

  return (
    <>
      {/* 라디오 그룹입니다. 버튼 8 개로 만들면 화살표 이동과 "하나만 고름"을 직접 구현해야
          하는데, 브라우저가 이미 하는 일입니다. */}
      <div className="art-style-grid" role="radiogroup" aria-label="화풍">
        {styles.map((style) => (
          <div
            key={style.artStyleId}
            className={style.artStyleId === value ? "art-style-card selected" : "art-style-card"}
          >
            {/* ⚠️ 확대 버튼은 이 `label` **밖**에 있습니다. 안에 두면 버튼을 눌러도 라벨이
                함께 활성화되어 화풍이 선택됩니다 - 크게 보려던 것이 고르는 행동이 됩니다. */}
            <label>
              <input
                type="radio"
                name={groupName}
                value={style.artStyleId}
                checked={style.artStyleId === value}
                onChange={() => onChange(style.artStyleId)}
              />
              <span className="art-style-thumb" aria-hidden="true">
                {style.exampleImageUrl === "" ? (
                  <em>예시 준비 중</em>
                ) : (
                  <img src={style.exampleImageUrl} alt="" loading="lazy" />
                )}
              </span>
              <span className="art-style-name">{style.name}</span>
            </label>

            {/* 예시가 없으면 확대할 것도 없습니다. 눌러 봐야 빈 화면인 버튼은 두지 않습니다. */}
            {style.exampleImageUrl !== "" && (
              <button
                type="button"
                className="art-style-zoom"
                aria-label={`${style.name} 예시 크게 보기`}
                onClick={() => setZoomed(style)}
              >
                <span aria-hidden="true">+</span>
              </button>
            )}
          </div>
        ))}
      </div>

      {/* DoD: "미선택 시 랜덤이 적용되고 그 사실이 보임". 고른 뒤에도 되돌릴 길을 둡니다 -
          라디오는 한 번 고르면 스스로 해제되지 않습니다. */}
      <div className="art-style-foot">
        <small>
          {value === ""
            ? "고르지 않으면 서버가 후보군에서 무작위로 채웁니다."
            : "선택한 화풍으로 생성합니다."}
        </small>
        {value !== "" && (
          <button type="button" className="link-button" onClick={() => onChange("")}>
            선택 해제
          </button>
        )}
      </div>

      {zoomed !== null && <ArtStyleZoom style={zoomed} onClose={() => setZoomed(null)} />}
    </>
  );
}

/**
 * 예시 한 장을 크게 봅니다.
 *
 * ⚠️ **여기서 화풍을 고를 수는 없습니다.** 크게 보는 것과 정하는 것은 다른 행동이고, 확대해
 * 놓고 닫으면 골라져 있는 화면은 사용자가 자기가 무엇을 했는지 알 수 없게 만듭니다.
 */
function ArtStyleZoom({ style, onClose }: { style: ArtStyle; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  // 열기 전에 어디에 있었는지 기억해 두었다가 닫을 때 돌려줍니다. 안 그러면 키보드 사용자가
  // 격자 처음으로 튕겨 나갑니다.
  const returnTo = useRef<Element | null>(null);

  useEffect(() => {
    returnTo.current = document.activeElement;
    closeRef.current?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);

    return () => {
      document.removeEventListener("keydown", onKey);
      (returnTo.current as HTMLElement | null)?.focus?.();
    };
  }, [onClose]);

  return (
    // 배경을 누르면 닫힙니다. 키보드에는 아래 닫기 버튼과 Escape 가 있으므로 이 요소에는
    // 따로 역할을 주지 않습니다.
    <div className="art-zoom-backdrop" onClick={onClose}>
      <div
        className="art-zoom"
        role="dialog"
        aria-modal="true"
        aria-label={`${style.name} 예시`}
        // 안쪽을 누른 것이 배경까지 올라가면 이미지를 누를 때마다 닫힙니다.
        onClick={(event) => event.stopPropagation()}
      >
        <div className="art-zoom-head">
          <strong>{style.name}</strong>
          <button ref={closeRef} type="button" className="link-button" onClick={onClose}>
            닫기
          </button>
        </div>
        <img src={style.exampleImageUrl} alt={`${style.name} 화풍 예시`} />
        <small>이 화면에서는 고르지 않습니다. 닫고 카드를 눌러 선택하세요.</small>
      </div>
    </div>
  );
}

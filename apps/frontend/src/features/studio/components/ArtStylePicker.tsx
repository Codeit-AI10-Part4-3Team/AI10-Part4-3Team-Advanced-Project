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
 *
 * ⚠️ **URL 이 있는데 못 불러오는 경우도 같은 자리로 갑니다** (#216). 파일이 아직 볼륨에
 * 없거나 이름이 어긋나면 그 URL 은 404 이고, `onError` 가 없으면 그 칸은 브라우저의 깨진
 * 그림이 됩니다. 운영 절차가 "파일이 먼저, URL 이 나중" 으로 그 상태를 막고 있지만
 * (infra/README.md), 절차가 아니라 화면이 버티게 하는 것이 이 처리입니다.
 */
export function ArtStylePicker({ styles, value, onChange }: ArtStylePickerProps) {
  // 같은 화면에 픽커가 둘 이상 있어도 라디오 그룹이 섞이지 않게 합니다.
  const groupName = useId();
  const [zoomed, setZoomed] = useState<ArtStyle | null>(null);

  // ⚠️ **`artStyleId` 가 아니라 URL 로 기억합니다.** 운영자가 파일을 넣고 URL 을 고치면 같은
  // 화풍에 새 URL 이 옵니다 - 식별자로 기억하면 그 카드는 고쳐진 뒤에도 영영 실패로 남습니다.
  // 실패한 것은 화풍이 아니라 그 주소입니다.
  const [failedUrls, setFailedUrls] = useState<ReadonlySet<string>>(() => new Set());
  const markFailed = (url: string) => {
    setFailedUrls((previous) => (previous.has(url) ? previous : new Set(previous).add(url)));
  };
  // 예시를 실제로 보여 줄 수 있는가. 빈 문자열(아직 안 옴)과 로드 실패(못 불러옴)를 함께
  // 거릅니다 - 확대 버튼과 다이얼로그가 이 판단 하나를 같이 씁니다.
  const hasExample = (style: ArtStyle) =>
    style.exampleImageUrl !== "" && !failedUrls.has(style.exampleImageUrl);

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
                {/* ⚠️ 두 문구를 가릅니다. 화면상 자리는 같지만 **원인이 다릅니다** - 빈
                    문자열은 "아직 안 왔다" 이고 실패는 "왔는데 못 불러왔다" 입니다. 2단계
                    전달을 하는 사람이 이 둘을 구분하지 못하면, URL 을 이미 채운 상태에서도
                    "아직 안 넣었나" 로 읽습니다 (infra/README.md 의 순서 규칙).
                    404 인지 권한 문제인지까지는 가르지 않습니다 - `<img>` 가 상태 코드를
                    주지 않아 화면에서 알 수 있는 방법이 없습니다 (#216). */}
                {style.exampleImageUrl === "" ? (
                  <em>예시 준비 중</em>
                ) : failedUrls.has(style.exampleImageUrl) ? (
                  <em>예시를 불러오지 못했습니다</em>
                ) : (
                  <img
                    src={style.exampleImageUrl}
                    alt=""
                    loading="lazy"
                    onError={() => markFailed(style.exampleImageUrl)}
                  />
                )}
              </span>
              <span className="art-style-name">{style.name}</span>
            </label>

            {/* 예시가 없으면 확대할 것도 없습니다. 눌러 봐야 빈 화면인 버튼은 두지 않습니다.
                못 불러온 경우도 같습니다 - 크게 봐도 같은 그림이 없습니다. */}
            {hasExample(style) && (
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

      {zoomed !== null && (
        <ArtStyleZoom
          style={zoomed}
          failed={!hasExample(zoomed)}
          onLoadError={() => markFailed(zoomed.exampleImageUrl)}
          onClose={() => setZoomed(null)}
        />
      )}
    </>
  );
}

/**
 * 예시 한 장을 크게 봅니다.
 *
 * ⚠️ **네이티브 `<dialog>` 를 `showModal()` 로 엽니다.** 포커스 가두기, Escape 닫기, 배경
 * 비활성화, 닫을 때 원래 자리로 포커스 되돌리기를 전부 브라우저가 합니다. 직접 만들었을
 * 때는 Tab 한 번에 배경 폼으로 빠져나갔고, 거기서 타이핑하면 **글자가 사라지고 포커스가
 * 확대창으로 튕겼습니다** (PR 179 리뷰에서 재현). Tab 이동은 z-index 가 아니라 DOM 순서를
 * 따르므로 덮어 놓는 것만으로는 막히지 않습니다.
 *
 * ⚠️ **여기서 화풍을 고를 수는 없습니다.** 크게 보는 것과 정하는 것은 다른 행동이고, 확대해
 * 놓고 닫으면 골라져 있는 화면은 사용자가 자기가 무엇을 했는지 알 수 없게 만듭니다.
 *
 * ⚠️ **여기서도 로드가 실패할 수 있습니다** (#216). 격자의 썸네일은 `loading="lazy"` 라
 * 화면 밖이면 아직 받아 본 적이 없고, 캐시가 만료된 뒤 열 수도 있습니다. 그래서 실패를
 * 부모에게 올려 두 자리가 같은 판단을 쓰게 합니다 - 그러지 않으면 다이얼로그는 실패를
 * 아는데 격자의 확대 버튼은 그대로 남습니다.
 */
function ArtStyleZoom({
  style,
  failed,
  onLoadError,
  onClose,
}: {
  style: ArtStyle;
  failed: boolean;
  onLoadError: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  // 의존성이 비어 있는 것이 중요합니다. `onClose` 를 넣으면 부모가 리렌더될 때마다
  // 정리와 재실행이 돌아 포커스가 흔들립니다 - 그 함수는 아래 이벤트 핸들러에서만 씁니다.
  useEffect(() => {
    const dialog = ref.current;
    // ⚠️ 열기 **전에** 기억합니다. `<dialog>` 가 닫을 때 포커스를 되돌려 주기는 하지만, 여기서는
    // React 가 요소를 떼어내며 닫으므로 그 복귀가 사라집니다 - 실측에서 `body` 로 갔습니다.
    const opener = document.activeElement as HTMLElement | null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      opener?.focus?.();
    };
  }, []);

  // ⚠️ **`close` 가 아니라 `cancel` 을 듣습니다.** `close` 는 우리가 부른 `close()` 에도
  // 발생하는데, StrictMode 는 효과를 두 번 돌리므로 정리 단계의 `close()` 가 곧바로
  // `onClose` 를 불러 **열자마자 닫힙니다**(실측). `cancel` 은 사용자가 Escape 로 닫을 때만
  // 발생합니다.

  return (
    <dialog
      ref={ref}
      className="art-zoom"
      aria-label={`${style.name} 예시`}
      onCancel={onClose}
      // ⚠️ 배경은 `::backdrop` 이라 클릭 대상이 dialog 자신입니다. 안쪽을 내용 요소가 덮고
      // 있어 `event.target` 비교로는 걸러지지 않으므로, 좌표가 상자 밖인지로 봅니다.
      onClick={(event) => {
        const box = ref.current?.getBoundingClientRect();
        if (box === undefined) return;
        const outside =
          event.clientX < box.left ||
          event.clientX > box.right ||
          event.clientY < box.top ||
          event.clientY > box.bottom;
        if (outside) onClose();
      }}
    >
      <div className="art-zoom-body">
        <div className="art-zoom-head">
          <strong>{style.name}</strong>
          <button type="button" className="link-button" onClick={onClose}>
            닫기
          </button>
        </div>
        {failed ? (
          // 다이얼로그를 스스로 닫지 않습니다. 열자마자 사라지면 사용자는 자기가 잘못
          // 눌렀다고 읽습니다 - 무엇이 없는지 말하고 닫는 것은 사용자에게 맡깁니다.
          <p className="art-zoom-missing">예시를 불러오지 못했습니다.</p>
        ) : (
          <img src={style.exampleImageUrl} alt={`${style.name} 화풍 예시`} onError={onLoadError} />
        )}
        <small>이 화면에서는 고르지 않습니다. 닫고 카드를 눌러 선택하세요.</small>
      </div>
    </dialog>
  );
}

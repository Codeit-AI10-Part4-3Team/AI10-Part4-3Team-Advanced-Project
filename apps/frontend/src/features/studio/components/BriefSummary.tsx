import { useEffect, useState, type FormEvent } from "react";
import { listArtStyles } from "../api";
import { OUTPUT_TYPE_LABEL } from "../labels";
import { ArtStylePicker } from "./ArtStylePicker";
import type { ArtStyle, Brief, BriefPatch, FieldMeta, Session } from "../types";

interface BriefSummaryProps {
  session: Session;
  /**
   * 브리프가 아직 잠기지 않았을 때만 참입니다 (INV-7).
   *
   * ⚠️ 이 값이 거짓인데 고치기를 열어 두면 저장에서 409 `STATE_CONFLICT` 가 돌아옵니다.
   * 눌러 봐야 알 수 있는 금지는 안내가 아니라 오류입니다 - 버튼 자체를 내립니다.
   */
  editable: boolean;
  onSave: (patch: BriefPatch) => Promise<void>;
}

/**
 * 서버가 채운 값에만 표시를 답니다.
 *
 * ⚠️ 사용자가 직접 쓴 값(`user`)에는 아무 표시도 하지 않습니다 - 전부에 딱지를 붙이면
 * 아무것도 구분되지 않습니다. 자동으로 채워진 값을 자기가 쓴 것으로 오해한 채 시안까지
 * 넘어가면 그 시점에는 브리프가 잠겨 되돌릴 수 없습니다 (INV-7).
 */
function FilledMark({ meta }: { meta?: FieldMeta }) {
  if (meta === undefined || meta.filledBy === "user") return null;
  const label = meta.filledBy === "inferred" ? "자동 추론" : "자동 지정";
  return <em className="filled-mark">{label}</em>;
}

/** `visibility` 가 정합니다. 화면이 필드마다 고칠 수 있는지를 따로 외우지 않습니다. */
function isEditable(meta?: FieldMeta): boolean {
  return meta?.visibility === "editable";
}

/**
 * `brief.artStyle` 은 **식별자**(`artStyleId`)입니다. 사람이 읽을 이름은 카탈로그에 있습니다.
 *
 * ⚠️ 식별자를 그대로 보여주면 계약의 식별자가 사용자 문구가 되어 이름을 못 바꾸게 됩니다
 * (labels.ts 가 `single_ad` 와 `queued` 에 대해 말하는 것과 같은 이유). 후보 목록이 비어 있던
 * 동안에는 이 값이 항상 빈 문자열이라 드러나지 않던 자리입니다.
 *
 * 목록에 없는 식별자는 **그대로 보여줍니다.** 후보가 바뀌어 옛 세션의 값이 사라진 경우인데,
 * 빈칸으로 두면 화풍이 지정된 적 없는 세션과 구분되지 않습니다.
 */
function artStyleName(artStyleId: string, catalog: ArtStyle[]): string {
  if (artStyleId === "") return "미지정";
  return catalog.find((style) => style.artStyleId === artStyleId)?.name ?? artStyleId;
}

/**
 * 편집 폼이 들고 있는 값. `Brief` 에서 **고칠 수 있는 것만** 남긴 모양입니다.
 *
 * ⚠️ `productImageUrl` 이 빠진 것은 실수가 아닙니다. `briefMeta` 는 그 필드를 `editable` 로
 * 표시하지만 계약의 `BriefPatch` 에는 자리가 없습니다 (재업로드 경로 미정, types.ts 참고).
 * 메타를 그대로 믿고 입력란을 만들면 저장이 422 로 거절됩니다.
 */
interface EditForm {
  productName: string;
  sellingPoint: string;
  note: string;
  category: string;
  target: string;
  artStyle: string;
  aspectRatio: string;
  characterAppearance: string;
  characterOutfit: string;
}

function toForm(brief: Brief): EditForm {
  return {
    productName: brief.productName,
    sellingPoint: brief.sellingPoint,
    note: brief.note,
    category: brief.category,
    target: brief.target,
    artStyle: brief.artStyle,
    aspectRatio: brief.aspectRatio ?? "",
    characterAppearance: brief.character?.appearance ?? "",
    characterOutfit: brief.character?.outfit ?? "",
  };
}

/**
 * 바뀐 키만 골라냅니다.
 *
 * ⚠️ **바뀌지 않은 키를 함께 보내면 안 됩니다.** 그 값도 서버에서 `filledBy: user` 로 바뀌어,
 * 자동으로 채워진 값이 사용자가 쓴 값으로 둔갑합니다. 고치기를 열었다 닫기만 해도 브리프의
 * 출처 기록이 사라지는 셈입니다.
 *
 * 빈 객체를 돌려줄 수 있습니다. 그때는 저장을 부르지 않습니다 - 계약이 `minProperties: 1`
 * 이라 빈 patch 는 422 입니다.
 */
function diff(brief: Brief, form: EditForm): BriefPatch {
  const patch: BriefPatch = {};

  if (form.productName !== brief.productName) patch.productName = form.productName;
  if (form.sellingPoint !== brief.sellingPoint) patch.sellingPoint = form.sellingPoint;
  if (form.note !== brief.note) patch.note = form.note;
  if (form.category !== brief.category) patch.category = form.category;
  if (form.target !== brief.target) patch.target = form.target;
  if (form.artStyle !== brief.artStyle) patch.artStyle = form.artStyle;

  // 출력 유형에 없는 필드는 키 자체가 없습니다. 없는 것을 보내면 422 입니다.
  if (brief.aspectRatio !== undefined && form.aspectRatio !== brief.aspectRatio) {
    patch.aspectRatio = form.aspectRatio;
  }
  if (
    brief.character !== undefined &&
    (form.characterAppearance !== brief.character.appearance ||
      form.characterOutfit !== brief.character.outfit)
  ) {
    // 계약의 `Character` 는 통째로 교체합니다. 한 쪽만 보내는 자리가 없습니다.
    patch.character = { appearance: form.characterAppearance, outfit: form.characterOutfit };
  }

  return patch;
}

export function BriefSummary({ session, editable, onSave }: BriefSummaryProps) {
  const { brief, briefMeta, outputType } = session;

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditForm>(() => toForm(brief));
  const [saving, setSaving] = useState(false);
  // 저장을 눌렀는데 보낼 것이 없을 때 무엇이 비었는지 말해 주는 자리입니다.
  const [hint, setHint] = useState<string | null>(null);
  const [artStyles, setArtStyles] = useState<ArtStyle[]>([]);

  // ⚠️ **후보 목록이 비어 있는 것이 지금은 정상입니다.** 목록은 확정됐지만(A-3) 설정
  // (`ADGEN_ART_STYLES`)에 값이 들어오지 않았고 예시 이미지도 없습니다. 화면이 후보를
  // 지어내면 그 값이 브리프에 저장되어 나중에 출처를 알 수 없게 됩니다 (apps/frontend/AGENTS.md).
  // 그림 격자로 고르는 것은 F2 의 몫이고, 여기서는 서버가 준 목록만 씁니다.
  useEffect(() => {
    let cancelled = false;

    listArtStyles()
      .then((next) => {
        if (!cancelled) setArtStyles(next);
      })
      .catch((error: unknown) => {
        // 화풍은 선택 항목입니다. 목록을 못 읽었다고 브리프 수정 전체를 막지 않습니다.
        if (!cancelled) console.warn("화풍 목록을 불러오지 못했습니다.", error);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // 잠긴 뒤에는 편집 화면을 내립니다. 시안이 생기는 경로는 다른 탭일 수도 있어
  // (`draft_generating` 안내 참고) 열어 둔 채로 잠길 수 있고, 그대로 저장하면 409 입니다.
  //
  // ⚠️ 효과 안에서 `setEditing(false)` 로 맞추지 않고 **렌더 중에 파생**합니다. 그쪽은 렌더가
  // 한 번 더 돌고 `react-hooks/set-state-in-effect` 에도 걸립니다.
  const isEditing = editing && editable;

  const update = <K extends keyof EditForm>(key: K, value: EditForm[K]) => {
    // 무엇이든 고치면 안내를 내립니다. 남겨 두면 이미 채운 사람에게 아직 비었다고 말합니다.
    setHint(null);
    setForm((current) => ({ ...current, [key]: value }));
  };

  function open() {
    // 열 때마다 서버의 최신 값으로 다시 채웁니다. 이전에 쓰다 만 값이 남아 있으면 그것이
    // 지금의 브리프인 줄 알고 저장하게 됩니다.
    setForm(toForm(brief));
    setHint(null);
    setEditing(true);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setHint(null);
    const patch = diff(brief, form);

    // 바뀐 것이 없으면 요청 자체를 만들지 않습니다 (계약이 `minProperties: 1`).
    if (Object.keys(patch).length === 0) {
      // ⚠️ **그냥 닫으면 안 되는 경우가 하나 있습니다.** `brief_filling` 은 시안을 만들 수
      // 없는 상태이고, 화면이 안내하는 유일한 탈출구가 이 폼입니다. 그런데 열화된 세션은
      // `category` 와 `target` 이 빈 문자열로 시작하므로(session_flow 의 상태 표), 사용자가
      // 아무것도 채우지 않고 저장을 누르면 patch 가 비어 조용히 닫힙니다. 브라우저 검증도
      // 서버 422 도 거치지 않아 **왜 안 넘어가는지 알 방법이 없습니다.**
      if (session.state === "brief_filling") {
        setHint(
          session.needsInput === undefined
            ? "카테고리와 타겟을 채워야 시안을 만들 수 있습니다."
            : "추가 메모를 채우면 자동 채움을 다시 시도합니다.",
        );
        return;
      }
      setEditing(false);
      return;
    }

    setSaving(true);
    try {
      await onSave(patch);
      setEditing(false);
    } catch {
      // 문구는 호출부의 오류 배너가 만듭니다. 여기서는 폼을 닫지 않는 것이 일입니다 -
      // 닫으면 사용자가 방금 친 값이 사라지고, 충돌이었다면 다시 칠 수도 없습니다.
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel brief-panel" aria-labelledby="brief-heading">
      <div className="panel-heading">
        <div>
          {/* ⚠️ 새 세션 화면의 **01 과 02 를 합친 결과**입니다 - 입력(01)과 화풍(02)이
              여기 한 칸에 모여 있습니다. 그래서 번호를 하나로 적지 않습니다. */}
          <p className="eyebrow">STEP 01 - 02</p>
          <h2 id="brief-heading">광고 브리프</h2>
        </div>
        {isEditing ? (
          <span>{OUTPUT_TYPE_LABEL[outputType]}</span>
        ) : (
          <div className="brief-heading-actions">
            <span>{OUTPUT_TYPE_LABEL[outputType]}</span>
            {editable && (
              <button type="button" className="link-button" onClick={open}>
                고치기
              </button>
            )}
          </div>
        )}
      </div>

      {/* ⚠️ 사진이 만료되면 `productImageUrl` 이 빈 문자열입니다 (보존 24시간, 세션은 7일).
          그때 `<img>` 를 그리면 404 를 받아 깨진 이미지가 남으므로, 값이 비었는지로 먼저
          분기합니다 - 만료를 응답이 아니라 이 필드로 알라는 것이 계약의 규칙입니다. */}
      {brief.productImageUrl === "" ? (
        <p className="image-expired">업로드한 사진의 보관 기간(24시간)이 지났습니다.</p>
      ) : (
        <img className="product-image" src={brief.productImageUrl} alt="업로드한 제품 사진" />
      )}

      {isEditing ? (
        <form className="brief-edit" onSubmit={(event) => void submit(event)}>
          {/* 사진 교체 자리는 두지 않습니다. 계약에 재업로드 경로가 없습니다 (types.ts 의
              `BriefPatch` 주석). 그 사실을 화면에도 적어 두어야 "왜 사진만 못 고치나"가
              결함으로 보고되지 않습니다. */}
          <p className="contract-note">
            사진은 아직 교체할 수 없습니다. 바꾸려면 새 세션으로 시작해 주세요.
          </p>

          {isEditable(briefMeta.productName) && (
            <label className="field">
              <span>제품명</span>
              <input
                value={form.productName}
                maxLength={40}
                required
                onChange={(event) => update("productName", event.target.value)}
              />
            </label>
          )}

          {isEditable(briefMeta.sellingPoint) && (
            <label className="field">
              <span>핵심 소구점</span>
              <textarea
                value={form.sellingPoint}
                maxLength={200}
                rows={3}
                required
                onChange={(event) => update("sellingPoint", event.target.value)}
              />
              {/* 여기 적은 것이 가드레일의 근거 원문입니다. 비어 있을수록 시안이 거절될
                  확률이 올라갑니다. */}
              <small>{form.sellingPoint.length}/200</small>
            </label>
          )}

          {isEditable(briefMeta.category) && (
            <label className="field">
              <span>카테고리</span>
              <input
                value={form.category}
                onChange={(event) => update("category", event.target.value)}
              />
            </label>
          )}

          {isEditable(briefMeta.target) && (
            <label className="field">
              <span>타겟</span>
              <input
                value={form.target}
                onChange={(event) => update("target", event.target.value)}
              />
            </label>
          )}

          {isEditable(briefMeta.artStyle) && (
            <div className="field">
              <span>화풍</span>
              {/* 생성 폼과 같은 픽커를 씁니다. 같은 값을 고르는 자리가 둘인데 모양이 다르면
                  어느 쪽이 진짜인지 사용자가 판단해야 합니다. */}
              <ArtStylePicker
                styles={artStyles}
                value={form.artStyle}
                onChange={(id) => update("artStyle", id)}
              />
            </div>
          )}

          {brief.aspectRatio !== undefined && isEditable(briefMeta.aspectRatio) && (
            <label className="field">
              <span>비율</span>
              <input
                value={form.aspectRatio}
                onChange={(event) => update("aspectRatio", event.target.value)}
              />
            </label>
          )}

          {brief.character !== undefined && isEditable(briefMeta.character) && (
            <>
              <label className="field">
                <span>캐릭터 외모</span>
                <input
                  value={form.characterAppearance}
                  onChange={(event) => update("characterAppearance", event.target.value)}
                />
              </label>
              <label className="field">
                <span>캐릭터 의상</span>
                <input
                  value={form.characterOutfit}
                  onChange={(event) => update("characterOutfit", event.target.value)}
                />
              </label>
            </>
          )}

          {isEditable(briefMeta.note) && (
            <label className="field">
              <span>추가 메모</span>
              <textarea
                value={form.note}
                maxLength={500}
                rows={3}
                onChange={(event) => update("note", event.target.value)}
              />
              {session.needsInput !== undefined && (
                // 되물음에 답하는 자리가 여기라는 것을 말해 줍니다. 계약이 "note 를 채우면
                // 서버가 추론을 다시 시도한다"고 정한 곳이 이 필드입니다.
                <small>여기를 채우면 자동 채움을 다시 시도합니다.</small>
              )}
            </label>
          )}

          {hint !== null && (
            <p className="notice notice-input" role="status">
              {hint}
            </p>
          )}

          <div className="brief-edit-actions">
            <button className="submit-button" type="submit" disabled={saving}>
              {saving ? "저장하는 중..." : "저장"}
            </button>
            <button
              type="button"
              className="link-button"
              disabled={saving}
              onClick={() => setEditing(false)}
            >
              취소
            </button>
          </div>
        </form>
      ) : (
        <dl className="brief-fields">
          <div>
            <dt>
              제품명 <FilledMark meta={briefMeta.productName} />
            </dt>
            <dd>{brief.productName}</dd>
          </div>
          <div>
            <dt>
              화풍 <FilledMark meta={briefMeta.artStyle} />
            </dt>
            <dd>{artStyleName(brief.artStyle, artStyles)}</dd>
          </div>
          <div className="wide">
            <dt>
              핵심 소구점 <FilledMark meta={briefMeta.sellingPoint} />
            </dt>
            <dd>{brief.sellingPoint}</dd>
          </div>
          <div>
            <dt>
              카테고리 <FilledMark meta={briefMeta.category} />
            </dt>
            <dd>{brief.category || "미정"}</dd>
          </div>
          <div>
            <dt>
              타겟 <FilledMark meta={briefMeta.target} />
            </dt>
            <dd>{brief.target || "미정"}</dd>
          </div>
          {brief.aspectRatio !== undefined && (
            <div>
              <dt>
                비율 <FilledMark meta={briefMeta.aspectRatio} />
              </dt>
              <dd>{brief.aspectRatio}</dd>
            </div>
          )}
          {brief.character !== undefined && (
            <div className="wide">
              <dt>
                캐릭터 <FilledMark meta={briefMeta.character} />
              </dt>
              <dd>{`${brief.character.appearance} / ${brief.character.outfit}`}</dd>
            </div>
          )}
          <div className="wide">
            <dt>
              추가 메모 <FilledMark meta={briefMeta.note} />
            </dt>
            <dd>{brief.note || "없음"}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

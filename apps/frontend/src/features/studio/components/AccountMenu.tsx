import { useEffect, useRef, useState } from "react";
import type { Me } from "../../auth/types";

interface AccountMenuProps {
  me: Me | null;
  onSignOut: () => void;
}

/**
 * 계정 정보와 로그아웃을 담는 사이드바 하단 메뉴.
 *
 * ⚠️ **적을 수 있는 것은 계약의 `Me` 가 주는 것뿐입니다** - `loginId` 와 `createdAt` 입니다.
 * 표시 이름과 이메일은 계약이 **두지 않기로 한 것**이지 아직 안 넣은 것이 아닙니다
 * (openapi.yaml 의 `Me`: "이메일은 두는 순간 개인정보 보관 항목이 하나 늡니다").
 *
 * ⚠️ **`<dialog>` 가 아닙니다.** 확대창(`ArtStylePicker`)과 달리 여기는 흐름을 막을 이유가
 * 없습니다 - 계정을 확인하는 동안 뒤의 세션 목록이 잠길 필요가 없고, 모달은 열 때마다
 * 배경을 비활성화해 "잠깐 보는" 행동에 과합니다.
 *
 * ⚠️ **메뉴 역할(`role="menu"`)을 붙이지 않았습니다.** 그 역할은 화살표 키 이동을
 * 약속하는 위젯의 것이고 여기는 버튼 하나입니다. 없는 조작을 약속하는 편이 아무 역할도
 * 붙이지 않는 것보다 나쁩니다 (PR #235 리뷰).
 *
 * ⚠️ **바깥 클릭은 `pointerdown` 으로 듣습니다.** `click` 으로 들으면 메뉴 항목을 누르는
 * 동작이 그 항목의 `onClick` 보다 먼저 바깥 닫기에 걸리는 순서 문제가 생깁니다. 그리고
 * 자기 자신 안에서 시작한 것은 걸러야 하므로 컨테이너 기준으로 봅니다.
 */
export function AccountMenu({ me, onSignOut }: AccountMenuProps) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    };
    // Escape 는 포커스를 버튼으로 되돌립니다. 되돌리지 않으면 키보드 사용자가 메뉴를 닫은
    // 뒤 문서 맨 앞에서 다시 Tab 을 시작하게 됩니다.
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="account" ref={boxRef}>
      {/* ⚠️ **트리거가 메뉴보다 DOM 앞에 있어야 합니다.** 위치는 `position: absolute` 가
          정하므로 순서를 바꿔도 보이는 자리는 같지만, Tab 순서는 DOM 을 따릅니다. 메뉴가
          앞이면 열고 나서 Tab 을 눌러도 항목이 아니라 사이드바 밖으로 나가고, 항목에
          닿으려면 Shift+Tab 으로 되돌아와야 합니다 (PR #235 리뷰, 신호정).

          ⚠️ 글리프가 장식이 아닙니다. 좁은 폭에서는 이 버튼의 글자가 `font-size: 0` 이
          되므로(styles.css 960px 구간), `.avatar` 가 남지 않으면 버튼이 빈 상자가 됩니다.
          `aria-label` 은 그 구간에서도 이름을 잃지 않게 합니다. */}
      <button
        type="button"
        ref={buttonRef}
        className="profile-button"
        aria-label="계정 메뉴"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((previous) => !previous)}
      >
        <span className="avatar" aria-hidden="true">
          {me?.loginId.slice(0, 1).toUpperCase() ?? "?"}
        </span>
        {me?.loginId ?? "계정 확인 중"}
      </button>

      {open && (
        // ⚠️ **`role="menu"` 가 아닙니다.** 그 역할은 화살표 키로 항목을 옮기는 위젯을
        // 약속하는데 여기는 그렇지 않고, 계정 정보 줄은 `menuitem` 이 아니라 `menu` 의
        // 자식으로 허용되지도 않습니다(ARIA 가 정한 것은 `menuitem` 계열과 `group`,
        // `separator` 뿐). 실제 모습 그대로 - 이름이 붙은 상자 안에 버튼 하나입니다.
        // 위치는 `styles.css` 가 정하며 620px 이하에서는 아래로 열립니다.
        <div className="account-menu" role="group" aria-label="계정">
          <div className="account-info">
            <strong>{me?.loginId ?? "계정 확인 중"}</strong>
            {/* 계약이 주는 나머지 하나입니다. 없는 필드를 채우려고 여기에 무엇을 더 적으면
                그때부터 계약이 아니라 구두 합의입니다 (apps/frontend/AGENTS.md). */}
            {me !== null && <small>가입 {joinedOn(me.createdAt)}</small>}
          </div>
          <button
            type="button"
            className="account-item"
            onClick={() => {
              setOpen(false);
              onSignOut();
            }}
          >
            로그아웃
          </button>
        </div>
      )}
    </div>
  );
}

/** 못 읽는 값은 그대로 보여 줍니다 - 화면이 날짜를 지어내지 않습니다. */
function joinedOn(createdAt: string): string {
  const at = new Date(createdAt);
  return Number.isNaN(at.getTime()) ? createdAt : at.toLocaleDateString("ko-KR");
}

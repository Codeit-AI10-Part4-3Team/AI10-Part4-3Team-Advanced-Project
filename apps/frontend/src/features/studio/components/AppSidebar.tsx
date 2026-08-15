import { useAuth } from "../../auth/useAuth";
import { mockSessions } from "../mock-data";

interface AppSidebarProps {
  onNewSession: () => void;
}

export function AppSidebar({ onNewSession }: AppSidebarProps) {
  const { me, signOut } = useAuth();

  return (
    <aside className="sidebar" aria-label="광고 세션 탐색">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">3</span>
        <span>행복한 3팀</span>
      </div>

      <button className="primary-action" type="button" onClick={onNewSession}>
        <span aria-hidden="true">＋</span> 새 광고 만들기
      </button>

      <label className="search-field">
        <span className="sr-only">세션 검색</span>
        <span aria-hidden="true">⌕</span>
        <input type="search" placeholder="세션 검색" />
      </label>

      <p className="sidebar-label">최근 세션</p>
      <nav className="session-list" aria-label="최근 세션">
        {mockSessions.map((session) => (
          <button className="session-item" type="button" key={session.sessionId}>
            <span className={`session-dot ${session.outputType}`} aria-hidden="true" />
            <span>
              <strong>{session.productName}</strong>
              <small>{session.outputType === "comic" ? "6컷 만화" : "단일 광고"}</small>
            </span>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        {/* 표시할 것은 `loginId` 뿐입니다. 계약의 `Me` 에 표시 이름도 이메일도 없고,
            그것은 아직 안 넣은 것이 아니라 두지 않기로 한 결정입니다. */}
        <button type="button" className="profile-button">
          <span className="avatar" aria-hidden="true">
            {me?.loginId.slice(0, 1).toUpperCase() ?? "?"}
          </span>
          {me?.loginId ?? "계정 확인 중"}
        </button>
        <button type="button" onClick={() => void signOut()}>
          로그아웃
        </button>
      </div>
    </aside>
  );
}

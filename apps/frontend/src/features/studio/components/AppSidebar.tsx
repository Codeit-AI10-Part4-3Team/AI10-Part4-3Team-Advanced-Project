import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/useAuth";
import { listSessions } from "../api";
import { OUTPUT_TYPE_LABEL } from "../labels";
import type { SessionSummary } from "../types";

export function AppSidebar() {
  const { me, signOut } = useAuth();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [query, setQuery] = useState("");
  const { pathname } = useLocation();

  // ⚠️ 경로가 바뀔 때마다 다시 읽습니다. 세션을 만들면 곧바로 `/sessions/{id}` 로 이동하므로
  // 이 한 줄이 "만든 세션이 목록에 나타난다"를 성립시킵니다. 생성 화면이 목록에 직접 항목을
  // 밀어 넣는 방법도 있지만, 그러면 서버가 준 목록과 화면이 만든 목록 둘이 생기고 새로고침
  // 한 번에 어긋납니다. 목록의 주인은 언제나 `GET /v1/sessions` 입니다.
  useEffect(() => {
    let cancelled = false;

    listSessions()
      .then((next) => {
        if (!cancelled) setSessions(next);
      })
      .catch((error: unknown) => {
        // 목록을 못 읽는 것으로 화면 전체를 막지 않습니다. 401 이면 `RequireAuth` 가 이미
        // 로그인 화면으로 보내는 중이고, 그 밖의 실패는 지금 하려는 일(새 세션 만들기)을
        // 방해하지 않습니다.
        if (!cancelled) console.warn("세션 목록을 불러오지 못했습니다.", error);
      });

    return () => {
      cancelled = true;
    };
  }, [pathname]);

  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (keyword === "") return sessions;
    return sessions.filter((session) => session.productName.toLowerCase().includes(keyword));
  }, [sessions, query]);

  return (
    <aside className="sidebar" aria-label="광고 세션 탐색">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">3</span>
        <span>행복한 3팀</span>
      </div>

      <NavLink className="primary-action" to="/">
        <span aria-hidden="true">＋</span> 새 광고 만들기
      </NavLink>

      <label className="search-field">
        <span className="sr-only">세션 검색</span>
        <span aria-hidden="true">⌕</span>
        <input
          type="search"
          placeholder="세션 검색"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>

      <p className="sidebar-label">최근 세션</p>
      <nav className="session-list" aria-label="최근 세션">
        {visible.map((session) => (
          <NavLink
            className={({ isActive }) => (isActive ? "session-item active" : "session-item")}
            to={`/sessions/${session.sessionId}`}
            key={session.sessionId}
          >
            <span className={`session-dot ${session.outputType}`} aria-hidden="true" />
            <span>
              <strong>{session.productName}</strong>
              <small>{OUTPUT_TYPE_LABEL[session.outputType]}</small>
            </span>
          </NavLink>
        ))}
        {visible.length === 0 && (
          <p className="session-empty">
            {sessions.length === 0 ? "아직 만든 광고가 없습니다." : "검색 결과가 없습니다."}
          </p>
        )}
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
        {/* ⚠️ 아이콘이 장식이 아닙니다. 좁은 폭에서는 `.sidebar-footer button` 의 글자가
            `font-size: 0` 이 되므로(styles.css 960px 구간), 이 글리프가 남지 않으면 버튼이
            빈 상자가 됩니다. `.profile-button` 이 `.avatar` 로 살아남는 것과 같은 방식입니다.
            `aria-label` 은 그 구간에서도 이름을 잃지 않게 합니다. */}
        <button
          type="button"
          className="logout-button"
          aria-label="로그아웃"
          onClick={() => void signOut()}
        >
          <span className="logout-mark" aria-hidden="true">
            ⏻
          </span>
          로그아웃
        </button>
      </div>
    </aside>
  );
}

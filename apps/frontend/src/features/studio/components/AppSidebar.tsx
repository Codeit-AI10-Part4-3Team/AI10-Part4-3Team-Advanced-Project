import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/useAuth";
import { AccountMenu } from "./AccountMenu";
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
        {/* ⚠️ **로그아웃이 이 안으로 들어갔습니다.** 예전에는 프로필 버튼과 나란한 별도
            버튼이었는데, 프로필 쪽에 `onClick` 이 없어 눌러도 아무 일이 없었습니다. 계정을
            누르는 사람이 기대하는 것이 로그아웃이라, 죽은 버튼에 동작을 주는 대신 둘을
            한 자리로 모았습니다. 계약의 `Me` 로 할 수 있는 행동이 이것 하나뿐입니다. */}
        <AccountMenu me={me} onSignOut={() => void signOut()} />
      </div>
    </aside>
  );
}

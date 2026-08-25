import { Link } from "react-router-dom";

/**
 * 없는 경로.
 *
 * ⚠️ **예전에는 이 자리가 `/` 로의 리다이렉트였습니다.** 그래서 오타든 옛 북마크든 조용히
 * 첫 화면에 도착했고, 사용자는 자기가 무엇을 잘못 열었는지 몰랐습니다. 더 나쁜 것은 그
 * 리다이렉트가 `RequireAuth` 보다 먼저 돌아서 **로그인 복귀 경로를 통째로 죽였다**는
 * 것입니다 - 되돌아갈 주소가 언제나 `/` 로 바뀐 뒤였습니다 (#114).
 *
 * ⚠️ **로그인 뒤에 두지 않았습니다.** 없는 주소를 확인하는 데 계정이 필요할 이유가 없고,
 * 그렇게 두면 오타 하나에 로그인을 요구한 뒤 404 를 보여 주게 됩니다. 이 화면은 아무것도
 * 조회하지 않으므로 드러나는 정보도 없습니다.
 */
export function NotFoundPage() {
  return (
    <main className="auth-shell">
      <div className="auth-card">
        <p className="eyebrow">404</p>
        <h1>없는 주소입니다</h1>
        <p className="auth-lead">
          주소를 다시 확인해 주세요. 세션 주소는 목록에서 다시 열 수 있습니다.
        </p>
        <Link className="submit-button" to="/">
          첫 화면으로
        </Link>
      </div>
    </main>
  );
}

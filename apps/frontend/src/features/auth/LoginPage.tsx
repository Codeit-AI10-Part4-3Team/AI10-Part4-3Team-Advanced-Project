import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { useAuth } from "./useAuth";

/**
 * 로그인 화면.
 *
 * ⚠️ **아이디 오류와 비밀번호 오류를 구분해 보여 주지 않습니다.** 서버가 둘 다
 * `INVALID_CREDENTIALS` 로 답하는 것이 계약이고(API_계약 6절), 화면이 문구로 갈라 놓으면
 * 서버가 감춘 아이디 존재 여부가 화면에서 새어 나갑니다.
 */
export function LoginPage() {
  const { status, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === "signed_in") {
    // 로그인한 채로 이 화면에 오면 원래 가려던 곳으로 돌려보냅니다.
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setSubmitting(true);
    try {
      await signIn(loginId, password);
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      void navigate(from, { replace: true });
    } catch (error: unknown) {
      setMessage(describe(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={(event) => void handleSubmit(event)}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            3
          </span>
          <span>행복한 3팀</span>
        </div>

        <h1>로그인</h1>
        <p className="auth-lead">발급받은 계정으로 들어옵니다.</p>

        <label className="field">
          <span>아이디</span>
          {/* ⚠️ `maxLength` 는 계약(`LoginRequest.loginId`, maxLength 64)을 따라간 값입니다.
              없으면 긴 아이디를 붙여넣은 사용자가 422 `INVALID_REQUEST` 를 받는데, 서버는
              빈 칸과 길이 초과에 같은 코드를 쓰므로 화면은 그 둘을 구분하지 못합니다.
              비밀번호에는 상한이 없어(계약상 `minLength: 1` 뿐) 여기에만 답니다. */}
          <input
            name="loginId"
            autoComplete="username"
            required
            maxLength={64}
            value={loginId}
            onChange={(event) => setLoginId(event.target.value)}
          />
        </label>

        <label className="field">
          <span>비밀번호</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        {/* 오류는 화면 우측 상단 고정 영역이 정본이지만(기획서 12.5), 로그인 실패는 이
            폼에서만 의미가 있고 다음 동작도 이 폼 안에 있습니다. `role="alert"` 로 스크린
            리더에도 전달합니다. */}
        {message !== null && (
          <p className="auth-error" role="alert">
            {message}
          </p>
        )}

        <button className="submit-button" type="submit" disabled={submitting}>
          {submitting ? "확인 중..." : "로그인"}
        </button>

        <p className="auth-note">
          계정 발급과 비밀번호 재설정은 아직 화면이 없습니다. 팀에 문의하세요.
        </p>
      </form>
    </main>
  );
}

function describe(error: unknown): string {
  if (!(error instanceof ApiError)) {
    // 서버에 닿지도 못한 경우입니다. `ApiError` 는 응답을 받은 뒤에만 만들어집니다.
    return "서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.";
  }
  if (error.code === "INVALID_CREDENTIALS") {
    return "아이디 또는 비밀번호가 올바르지 않습니다.";
  }
  if (error.code === "INVALID_REQUEST") {
    // ⚠️ "모두 입력하세요"라고 단정하지 않습니다. 서버는 빈 칸과 길이 초과에 같은
    // `INVALID_REQUEST` 를 쓰므로, 두 칸을 채운 사용자에게 채우라고 말하는 경우가
    // 생깁니다. 원인을 특정할 수 없을 때는 특정하지 않는 문구가 정확합니다.
    return "아이디와 비밀번호를 확인하세요.";
  }
  return error.message;
}

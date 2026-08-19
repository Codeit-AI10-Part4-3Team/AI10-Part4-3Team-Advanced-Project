import { Outlet } from "react-router-dom";
import { AppSidebar } from "./features/studio/components/AppSidebar";

// 로그인한 뒤의 껍데기입니다. 사이드바는 화면이 바뀌어도 남아 있어야 하므로 여기서 한 번만
// 그리고, 안쪽만 `Outlet` 으로 갈아 끼웁니다 - 화면마다 사이드바를 다시 그리면 세션 목록을
// 이동할 때마다 처음부터 다시 읽습니다.
function App() {
  return (
    <main className="app-shell">
      <AppSidebar />
      <div className="workspace">
        <Outlet />
      </div>
    </main>
  );
}

export default App;

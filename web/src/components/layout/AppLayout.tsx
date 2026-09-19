import { Outlet, useLocation } from "react-router-dom";
import { LeftNav } from "./LeftNav";
import { TopBar } from "./TopBar";

// 全局布局：左栏菜单 + TopBar + 主区（无右栏）。
// 任务列表（根路径 /）列多，单独撑满主区宽度；其余页面收敛到 max-w-7xl 居中。
export function AppLayout() {
  const { pathname } = useLocation();
  const fullWidth = pathname === "/";
  return (
    <div className="flex h-screen overflow-hidden">
      <LeftNav />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <main className="flex-1 overflow-y-auto p-6">
          <div className={`${fullWidth ? "w-full" : "max-w-7xl mx-auto"} fade-in`}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

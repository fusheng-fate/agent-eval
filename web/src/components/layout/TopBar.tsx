import { useLocation } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { cn } from "../../lib/utils";

const titles: Array<[string, string]> = [
  ["/runs/", "任务详情"],
  ["/evaluator", "评估体系"],
  ["/datasets", "数据集"],
  ["/execution", "评测执行"],
  ["/reports", "报告中心"],
  ["/configs", "配置中心"],
];

function titleFor(pathname: string): string {
  if (pathname === "/") return "任务中心";
  for (const [prefix, t] of titles) if (pathname.startsWith(prefix)) return t;
  return "Agent 评测平台";
}

export function TopBar() {
  const { user, isAdmin, logout } = useAuth();
  const { pathname } = useLocation();
  return (
    <header className="h-12 shrink-0 bg-[var(--color-surface)] border-b border-[var(--color-border)] flex items-center justify-between px-4">
      <h1 className="text-[11px] font-bold text-[var(--color-title)] m-0">{titleFor(pathname)}</h1>
      <div className="flex items-center gap-4">
        {user && (
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-full bg-[var(--color-surface-alt)] text-[var(--color-title)] text-[11px] font-medium flex items-center justify-center">
              {(user.display_name || user.username).slice(0, 1).toUpperCase()}
            </span>
            <span className="text-[11px] text-[var(--color-title)]">{user.display_name || user.username}</span>
            <span
              className={cn(
                "px-2 py-0.5 rounded-[var(--radius-full)] text-[11px] font-medium",
                isAdmin ? "bg-[#E8F0FE] text-[var(--intl-blue)]" : "bg-[#F0F2F5] text-[var(--color-muted)]"
              )}
            >
              {isAdmin ? "管理员" : "普通用户"}
            </span>
          </div>
        )}
        <button
          onClick={logout}
          className="flex items-center gap-1.5 text-[11px] text-[var(--color-body)] hover:text-[var(--brand)] cursor-pointer"
        >
          <LogOut size={16} />
          退出登录
        </button>
      </div>
    </header>
  );
}

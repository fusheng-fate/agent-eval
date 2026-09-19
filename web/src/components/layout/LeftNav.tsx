import { useState } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  SlidersHorizontal,
  Database,
  PlayCircle,
  FileBarChart,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { cn } from "../../lib/utils";
import logoUrl from "../../assets/logo.svg";

const items = [
  { to: "/", label: "任务中心", icon: LayoutDashboard, end: true },
  { to: "/evaluator", label: "评估体系", icon: SlidersHorizontal },
  { to: "/datasets", label: "数据集", icon: Database },
  { to: "/execution", label: "评测执行", icon: PlayCircle },
  { to: "/reports", label: "报告中心", icon: FileBarChart },
  { to: "/configs", label: "配置中心", icon: Settings },
];

const STORAGE_KEY = "leftnav_collapsed";

export function LeftNav() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggle = () => {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  return (
    <nav
      className={cn(
        "shrink-0 bg-[var(--color-surface-alt)] border-r border-[var(--color-border)] flex flex-col py-4 transition-[width] duration-200",
        collapsed ? "w-14" : "w-44"
      )}
    >
      <div className={cn("flex items-center gap-2 mb-4", collapsed ? "justify-center px-0" : "px-4")}>
        <img src={logoUrl} alt="logo" className="w-6 h-6 object-contain shrink-0" />
        <span
          className={cn(
            "text-[13px] font-semibold text-[var(--color-title)] whitespace-nowrap overflow-hidden transition-opacity duration-200",
            collapsed ? "opacity-0 w-0" : "opacity-100"
          )}
        >
          Agent 评测平台
        </span>
      </div>
      <div className="flex flex-col gap-1 px-2">
        {items.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={label}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 h-10 px-3 rounded-[8px] text-[11px] transition-colors",
                collapsed && "justify-center px-0",
                isActive
                  ? "bg-[var(--color-surface)] text-[var(--color-title)] font-medium shadow-[var(--shadow-sm)]"
                  : "text-[var(--color-body)] hover:bg-[var(--color-hover)]"
              )
            }
          >
            <Icon size={20} className="shrink-0" />
            <span className={cn("whitespace-nowrap overflow-hidden transition-all duration-200", collapsed ? "w-0 opacity-0" : "opacity-100")}>
              {label}
            </span>
          </NavLink>
        ))}
      </div>
      <button
        onClick={toggle}
        title={collapsed ? "展开菜单" : "收起菜单"}
        className="mt-auto ml-auto mr-2 h-7 w-7 inline-flex items-center justify-center rounded-[6px] text-[var(--color-muted)] hover:bg-[var(--color-hover)] hover:text-[var(--color-title)] cursor-pointer"
      >
        {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
      </button>
    </nav>
  );
}

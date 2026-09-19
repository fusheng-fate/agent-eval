import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

// 全局状态徽章：pending 灰 / running 蓝(转圈) / paused 黄 / passed|done 绿 / failed|error 红 / stopped 灰
type Tone = "gray" | "blue" | "yellow" | "green" | "red";

const toneCls: Record<Tone, string> = {
  gray: "bg-[#F0F2F5] text-[var(--color-muted)]",
  blue: "bg-[#E8F0FE] text-[var(--intl-blue)]",
  yellow: "bg-[#FDF6EC] text-[var(--color-warning)]",
  green: "bg-[#E7F7EC] text-[var(--color-success)]",
  red: "bg-[#FDECEC] text-[var(--color-error)]",
};

const map: Record<string, { tone: Tone; label: string; spin?: boolean }> = {
  pending: { tone: "gray", label: "待执行" },
  running: { tone: "blue", label: "执行中", spin: true },
  queued: { tone: "gray", label: "排队中" },
  executed: { tone: "blue", label: "待评分", spin: true },
  scoring: { tone: "blue", label: "评分中", spin: true },
  paused: { tone: "yellow", label: "已暂停" },
  done: { tone: "green", label: "已完成" },
  stopped: { tone: "gray", label: "已停止" },
  error: { tone: "red", label: "异常" },
  passed: { tone: "green", label: "通过" },
  failed: { tone: "red", label: "失败" },
  skipped: { tone: "gray", label: "跳过" },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const m = map[status] ?? { tone: "gray" as Tone, label: status };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2.5 py-0.5 rounded-[var(--radius-full)] text-[11px] font-medium whitespace-nowrap",
        toneCls[m.tone],
        className
      )}
    >
      {m.spin && <Loader2 size={12} className="animate-spin" />}
      {m.label}
    </span>
  );
}

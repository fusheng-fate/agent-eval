import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

export function EmptyState({ title = "暂无数据", hint, action }: { title?: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <Inbox size={40} className="text-[var(--color-border)] mb-3" />
      <div className="text-[var(--color-muted)] text-[11px]">{title}</div>
      {hint && <div className="text-[11px] text-[var(--color-muted)] mt-1">{hint}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

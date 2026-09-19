// 分数进度条：>=80 绿 / >=60 黄 / else 红（百分制）。
import { cn } from "../../lib/utils";

export function scoreColor(score: number): string {
  if (score >= 80) return "var(--color-success)";
  if (score >= 60) return "var(--color-warning)";
  return "var(--color-error)";
}

export function ScoreBar({ score, max = 100, className }: { score: number; max?: number; className?: string }) {
  const pct = Math.max(0, Math.min(100, (score / max) * 100));
  return (
    <div className={cn("h-2 w-full bg-[var(--color-surface-alt)] rounded-full overflow-hidden", className)}>
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${pct}%`, background: scoreColor(score) }}
      />
    </div>
  );
}

import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function KpiCard({
  label,
  value,
  unit,
  tone,
  className,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  tone?: "default" | "success" | "error" | "warning";
  className?: string;
}) {
  const color =
    tone === "success"
      ? "var(--color-success)"
      : tone === "error"
        ? "var(--color-error)"
        : tone === "warning"
          ? "var(--color-warning)"
          : "var(--color-title)";
  return (
    <div className={cn("bg-[var(--color-surface-alt)] rounded-xl px-4 py-4 text-center", className)}>
      <div className="text-[20px] font-semibold" style={{ color }}>
        {value}
        {unit && <span className="text-[11px] font-normal ml-0.5 text-[var(--color-muted)]">{unit}</span>}
      </div>
      <div className="text-[11px] text-[var(--color-muted)] mt-1">{label}</div>
    </div>
  );
}

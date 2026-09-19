import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Card({
  title,
  extra,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <div
      className={cn(
        "bg-[var(--color-surface)] border border-[var(--color-border)] rounded-[var(--radius-card)] p-5",
        className
      )}
    >
      {(title || extra) && (
        <div className="flex items-center justify-between mb-4">
          {title && (
            <h2 className="text-[17px] font-semibold text-[var(--color-title)] m-0">{title}</h2>
          )}
          {extra && <div className="flex items-center gap-2">{extra}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
}

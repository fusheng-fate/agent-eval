import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

type Variant = "primary" | "ghost" | "outline" | "danger" | "link";

const base =
  "inline-flex items-center justify-center gap-1.5 h-9 px-3.5 rounded-[var(--radius-form)] text-[11px] font-medium whitespace-nowrap transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer";

const variants: Record<Variant, string> = {
  primary: "bg-[var(--brand)] text-white hover:bg-[var(--brand-hover)]",
  ghost: "bg-transparent text-[var(--color-body)] hover:bg-[var(--color-hover)]",
  outline: "bg-white border border-[var(--input-border)] text-[var(--color-body)] hover:border-[var(--brand)] hover:text-[var(--brand)]",
  danger: "bg-[var(--color-error)] text-white hover:opacity-90",
  link: "h-auto px-0 bg-transparent text-[var(--color-body)] underline hover:text-[var(--link)]",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  children: ReactNode;
}

export function Button({ variant = "primary", className, children, ...rest }: Props) {
  return (
    <button className={cn(base, variants[variant], className)} {...rest}>
      {children}
    </button>
  );
}

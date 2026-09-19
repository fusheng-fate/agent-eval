import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

const fieldBase =
  "w-full h-10 px-3 rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)] disabled:bg-[var(--color-surface-alt)] disabled:text-[var(--color-muted)]";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(fieldBase, className)} {...rest} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(fieldBase, "h-auto min-h-[80px] py-2 leading-relaxed", className)}
      {...rest}
    />
  );
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(fieldBase, "cursor-pointer", className)} {...rest}>
      {children}
    </select>
  );
}

export function Field({
  label,
  required,
  children,
  hint,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="block text-[11px] text-[var(--color-body)] mb-1.5">
        {label}
        {required && <span className="text-[var(--color-error)] ml-0.5">*</span>}
      </span>
      {children}
      {hint && <span className="block text-[11px] text-[var(--color-muted)] mt-1">{hint}</span>}
    </label>
  );
}

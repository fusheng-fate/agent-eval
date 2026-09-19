import { cn } from "../../lib/utils";

// 权重步进器：slider + 可编辑数字（step 0.05）。
export function Stepper({
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.05,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}) {
  const clamp = (v: number) => Math.min(max, Math.max(min, Math.round(v / step) * step));
  return (
    <div className={cn("flex items-center gap-3", disabled && "opacity-60")}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(clamp(parseFloat(e.target.value)))}
        className="flex-1 accent-[var(--brand)]"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (!Number.isNaN(v)) onChange(clamp(v));
        }}
        className="w-20 h-8 px-2 rounded-[var(--radius-form)] border border-[var(--input-border)] text-[11px] text-[var(--color-title)] text-center focus:outline-none focus:border-[var(--border-focus)]"
      />
    </div>
  );
}

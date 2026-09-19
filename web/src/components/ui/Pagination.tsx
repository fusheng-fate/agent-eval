import { ChevronLeft, ChevronRight } from "lucide-react";

export function Pagination({
  page,
  size,
  total,
  onChange,
  sizeOptions,
  onSizeChange,
}: {
  page: number;
  size: number;
  total: number;
  onChange: (page: number) => void;
  /** 提供后显示「每页 N 条」下拉；缺省不显示（纯翻页）。 */
  sizeOptions?: number[];
  onSizeChange?: (size: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1 && (!sizeOptions || sizeOptions.length <= 1)) return null;
  const btn =
    "h-8 w-8 inline-flex items-center justify-center rounded-[var(--radius-form)] border border-[var(--input-border)] text-[11px] text-[var(--color-body)] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer hover:border-[var(--brand)]";
  return (
    <div className="flex items-center justify-end gap-3 mt-4">
      {sizeOptions && onSizeChange && (
        <label className="flex items-center gap-1.5 text-[11px] text-[var(--color-muted)]">
          每页
          <select
            className="h-8 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2 text-[11px] text-[var(--color-body)] bg-white cursor-pointer"
            value={size}
            onChange={(e) => onSizeChange(Number(e.target.value))}
          >
            {sizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          条
        </label>
      )}
      <button className={btn} disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <ChevronLeft size={16} />
      </button>
      <span className="text-[11px] text-[var(--color-muted)]">
        {page} / {pages}
      </span>
      <button className={btn} disabled={page >= pages} onClick={() => onChange(page + 1)}>
        <ChevronRight size={16} />
      </button>
    </div>
  );
}

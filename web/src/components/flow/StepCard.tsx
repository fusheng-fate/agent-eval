// 单个步骤卡片（id / api_id select / optional / inputs）。受控组件。
// 移植自 reference/legacy/page-src/.../apiChain/StepCard.tsx，按 DESIGN.md 重着色。
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { cn } from "../../lib/utils";
import type { ApiSchema, Step } from "./types";
import { KeyValueEditor } from "./KeyValueEditor";

type StepCardProps = {
  value: Step;
  index: number;
  total: number;
  apis: ApiSchema[];
  onChange: (next: Step) => void;
  onDelete: () => void;
  onMove: (dir: -1 | 1) => void;
};

const inputCls = "rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";
const labelCls = "mb-0.5 block text-[8px] text-[var(--color-muted)]";

export function StepCard({ value, index, total, apis, onChange, onDelete, onMove }: StepCardProps) {
  const s = value;

  function patch(p: Partial<Step>) {
    onChange({ ...s, ...p });
  }

  return (
    <div className="rounded-[var(--radius-form)] border border-[var(--color-border)] bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-[var(--color-surface-alt)] px-2 py-0.5 text-[8px] font-semibold text-[var(--color-body)]">
          步骤 {index + 1}
        </span>
        <input
          value={s.id}
          onChange={(e) => patch({ id: e.target.value })}
          placeholder="步骤id"
          className={cn(inputCls, "w-28")}
        />
        <select
          value={s.api_id}
          onChange={(e) => patch({ api_id: e.target.value })}
          className={cn(inputCls, "w-44")}
        >
          {apis.length === 0 && <option value="">(请先添加 API)</option>}
          {apis.map((a) => (
            <option key={a.id} value={a.id}>{a.id}</option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-[8px] text-[var(--color-body)]">
          <input
            type="checkbox"
            checked={!!s.optional}
            onChange={(e) => patch({ optional: e.target.checked })}
            className="h-3.5 w-3.5"
          />
          optional
        </label>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => onMove(-1)}
            title="上移"
            className="rounded-[var(--radius-form)] border border-[var(--input-border)] p-1 text-[var(--color-body)] hover:bg-[var(--color-hover)] disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
          >
            <ArrowUp className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            disabled={index === total - 1}
            onClick={() => onMove(1)}
            title="下移"
            className="rounded-[var(--radius-form)] border border-[var(--input-border)] p-1 text-[var(--color-body)] hover:bg-[var(--color-hover)] disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
          >
            <ArrowDown className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2 py-1 text-[11px] text-[var(--color-error)] hover:bg-[var(--color-hover)] cursor-pointer"
          >
            <Trash2 className="h-3 w-3" /> 删除
          </button>
        </div>
      </div>

      <div className="mt-3">
        <label className={labelCls}>inputs（占位符填充值）</label>
        <KeyValueEditor
          value={s.inputs || {}}
          onChange={(inputs) => patch({ inputs })}
          keyPlaceholder="占位符名"
          valuePlaceholder="字面量或 {{steps.x.y}}"
        />
      </div>
    </div>
  );
}

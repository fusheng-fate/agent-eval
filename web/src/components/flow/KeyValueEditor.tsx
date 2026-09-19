// 通用键值行编辑器（headers / query / extract / inputs 复用）。受控组件。
import { useRef, type ReactNode } from "react";
import { cn } from "../../lib/utils";

type KeyValueEditorProps = {
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  addLabel?: string;
  className?: string;
  renderValueExtra?: (key: string, value: string) => ReactNode;
};

let _uid = 0;
function genId() {
  return `kv_${++_uid}_${Date.now().toString(36)}`;
}

const cellCls = "rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";

export function KeyValueEditor({
  value,
  onChange,
  keyPlaceholder = "键",
  valuePlaceholder = "值",
  addLabel = "+ 添加",
  className,
  renderValueExtra,
}: KeyValueEditorProps) {
  const entries = Object.entries(value || {});
  const rowIdRef = useRef<Map<string, string>>(new Map());

  function getRowId(key: string): string {
    let id = rowIdRef.current.get(key);
    if (!id) {
      id = genId();
      rowIdRef.current.set(key, id);
    }
    return id;
  }

  function updateKey(oldKey: string, newKey: string) {
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(value)) {
      next[k === oldKey ? newKey : k] = v;
    }
    const rowId = rowIdRef.current.get(oldKey);
    if (rowId) {
      rowIdRef.current.delete(oldKey);
      rowIdRef.current.set(newKey, rowId);
    }
    onChange(next);
  }

  function updateValue(key: string, v: string) {
    onChange({ ...value, [key]: v });
  }

  function removeKey(key: string) {
    const next = { ...value };
    delete next[key];
    rowIdRef.current.delete(key);
    onChange(next);
  }

  function addRow() {
    let key = "key";
    let i = 1;
    while (key in (value || {})) key = `key${++i}`;
    onChange({ ...value, [key]: "" });
  }

  return (
    <div className={cn("space-y-1.5", className)}>
      {entries.map(([k, v]) => (
        <div key={getRowId(k)} className="flex items-center gap-1.5">
          <input
            value={k}
            onChange={(e) => updateKey(k, e.target.value)}
            placeholder={keyPlaceholder}
            className={cn(cellCls, "w-1/3")}
          />
          <input
            value={v}
            onChange={(e) => updateValue(k, e.target.value)}
            placeholder={valuePlaceholder}
            className={cn(cellCls, "flex-1")}
          />
          {renderValueExtra && (
            <span onClick={(e) => e.stopPropagation()}>{renderValueExtra(k, v)}</span>
          )}
          <button
            type="button"
            onClick={() => removeKey(k)}
            title="删除"
            className="shrink-0 rounded-[var(--radius-form)] border border-[var(--input-border)] px-1.5 py-1 text-[11px] text-[var(--color-error)] hover:bg-[var(--color-hover)] cursor-pointer"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={addRow}
        className="rounded-[var(--radius-form)] border border-dashed border-[var(--input-border)] px-2 py-1 text-[11px] text-[var(--color-body)] hover:bg-[var(--color-hover)] cursor-pointer"
      >
        {addLabel}
      </button>
    </div>
  );
}

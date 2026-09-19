// final_extract 可视化编辑器（受控组件，v1.3）。
// 两种形态：
//   - string：JSONPath，从最后一步响应提取单字段（兼容旧）
//   - dict：跨步骤多字段，{字段名: {step, path}}
// 步骤序号缺省 = 最后一步；step 选项 = 各步骤（index+1 显示，0-based 存储）。
import { Plus, Trash2 } from "lucide-react";
import { cn } from "../../lib/utils";
import type { FinalExtract, FinalExtractField, Step } from "./types";

type Props = {
  value: FinalExtract | undefined;
  steps: Step[];
  apis: { id: string; name?: string }[];
  onChange: (next: FinalExtract | undefined) => void;
};

const cellCls = "rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";
const labelCls = "mb-0.5 block text-[8px] text-[var(--color-muted)]";

/** 步骤下拉选项：value=0-based 序号（""=缺省最后一步），label 含步骤序号 + api_id */
function stepOptions(steps: Step[], apis: { id: string; name?: string }[]) {
  const apiName = (id: string) => apis.find((a) => a.id === id)?.name || id;
  return steps.map((s, i) => ({
    value: String(i),
    label: `步骤${i + 1} · ${apiName(s.api_id)}`,
  }));
}

export function FinalExtractEditor({ value, steps, apis, onChange }: Props) {
  // enabled = 是否配置了 final_extract 字段（undefined = 未配置）。
  // 注意："" 是「已启用 + string 形态 + 空 path」的合法状态，必须算 enabled，
  // 否则勾选后 checked 仍为 false，看着像点不动。
  const enabled = value !== undefined;
  const isDict = enabled && typeof value === "object";
  const isString = enabled && typeof value === "string";
  const lastIdx = steps.length - 1;

  function setEnabled(on: boolean) {
    if (!on) {
      // 关闭：清空
      onChange(undefined);
      return;
    }
    // 开启：无条件设为空串（string 形态默认），不依赖 enabled 闭包，
    // 避免 onChange 同步更新但 enabled 仍是旧值导致 checkbox 视觉态不跟随。
    onChange("");
  }

  function switchToDict() {
    // string → dict：把现有 string 当作从最后一步取的字段 "result"
    if (isString) {
      onChange({ result: { step: lastIdx, path: value as string } });
    } else {
      onChange({});
    }
  }

  function switchToString() {
    // dict → string：取第一个字段的 path（丢 step 信息）
    if (isDict) {
      const first = Object.entries(value as Record<string, FinalExtractField>)[0];
      onChange(first ? first[1].path : "");
    }
  }

  // ---- dict 形态操作 ----
  function addField() {
    const cur = (isDict ? value : {}) as Record<string, FinalExtractField>;
    let name = "field";
    let i = 1;
    while (name in cur) name = `field${++i}`;
    onChange({ ...cur, [name]: { step: lastIdx, path: "" } });
  }

  function patchField(name: string, p: Partial<FinalExtractField>) {
    const cur = (isDict ? value : {}) as Record<string, FinalExtractField>;
    onChange({ ...cur, [name]: { ...cur[name], ...p } });
  }

  function renameField(oldName: string, newName: string) {
    const cur = (isDict ? value : {}) as Record<string, FinalExtractField>;
    if (newName === oldName || newName in cur) return;
    const next: Record<string, FinalExtractField> = {};
    for (const [k, v] of Object.entries(cur)) next[k === oldName ? newName : k] = v;
    onChange(next);
  }

  function removeField(name: string) {
    const cur = { ...(isDict ? value : {}) } as Record<string, FinalExtractField>;
    delete cur[name];
    onChange(cur);
  }

  const opts = stepOptions(steps, apis);

  return (
    <div className="rounded-[var(--radius-form)] border border-[var(--color-border)] bg-white p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] font-bold text-[var(--color-title)]">最终输出提取（final_extract）</div>
        <label className="flex items-center gap-1.5 text-[8px] text-[var(--color-body)] cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--brand)]"
          />
          启用（不启用则返回最后一步完整响应）
        </label>
      </div>

      {!enabled ? (
        <div className="text-[8px] text-[var(--color-muted)]">
          跑完流程后只取选定参数作为 agent_output 进评分；留空则用最后一步完整响应。
        </div>
      ) : (
        <div className="space-y-2">
          {/* 形态切换 */}
          <div className="flex items-center gap-2">
            <span className="text-[8px] text-[var(--color-muted)]">形态</span>
            <div className="flex rounded-[var(--radius-form)] border border-[var(--input-border)] overflow-hidden">
              <button
                type="button"
                onClick={() => !isString && switchToString()}
                className={cn(
                  "px-2.5 py-1 text-[11px] font-medium cursor-pointer",
                  isString ? "bg-[var(--brand)] text-white" : "bg-white text-[var(--color-body)] hover:bg-[var(--color-hover)]"
                )}
              >
                单字段
              </button>
              <button
                type="button"
                onClick={() => !isDict && switchToDict()}
                className={cn(
                  "px-2.5 py-1 text-[11px] font-medium cursor-pointer border-l border-[var(--input-border)]",
                  isDict ? "bg-[var(--brand)] text-white" : "bg-white text-[var(--color-body)] hover:bg-[var(--color-hover)]"
                )}
              >
                多字段（跨步骤）
              </button>
            </div>
          </div>

          {isString && (
            <div>
              <label className={labelCls}>JSONPath（从最后一步响应提取）</label>
              <input
                value={value as string}
                onChange={(e) => onChange(e.target.value)}
                placeholder="如 data.answer"
                className={cn(cellCls, "w-full")}
              />
            </div>
          )}

          {isDict && (
            <div className="space-y-1.5">
              {(Object.entries(value as Record<string, FinalExtractField>)).map(([name, f]) => (
                <div key={name} className="flex items-center gap-1.5">
                  <input
                    value={name}
                    onChange={(e) => renameField(name, e.target.value)}
                    placeholder="字段名"
                    className={cn(cellCls, "w-28")}
                  />
                  <select
                    value={f.step === undefined ? "" : String(f.step)}
                    onChange={(e) =>
                      patchField(name, e.target.value === "" ? { step: undefined } : { step: Number(e.target.value) })
                    }
                    className={cn(cellCls, "w-40")}
                  >
                    <option value="">最后一步（缺省）</option>
                    {opts.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <input
                    value={f.path}
                    onChange={(e) => patchField(name, { path: e.target.value })}
                    placeholder="JSONPath，如 data.token"
                    className={cn(cellCls, "flex-1")}
                  />
                  <button
                    type="button"
                    onClick={() => removeField(name)}
                    title="删除"
                    className="shrink-0 rounded-[var(--radius-form)] border border-[var(--input-border)] p-1 text-[var(--color-error)] hover:bg-[var(--color-hover)] cursor-pointer"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={addField}
                className="flex items-center gap-1 rounded-[var(--radius-form)] border border-dashed border-[var(--input-border)] px-2 py-1 text-[11px] text-[var(--color-body)] hover:bg-[var(--color-hover)] cursor-pointer"
              >
                <Plus className="h-3 w-3" /> 添加字段
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

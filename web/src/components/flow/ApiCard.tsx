// 单个 API 卡片（method/url/headers/query/body/timeout/on_error/retry/extract/auth）。受控组件。
// 移植自 reference/legacy/page-src/.../apiChain/ApiCard.tsx，按 DESIGN.md 重着色。
import { useRef, useState } from "react";
import { AlignLeft, ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { cn } from "../../lib/utils";
import { HTTP_METHODS, ensureAuth, type ApiSchema, type ChainModel } from "./types";
import { AutoResizeTextarea } from "./AutoResizeTextarea";
import { KeyValueEditor } from "./KeyValueEditor";
import { AuthEditor } from "./AuthEditor";
import { PlaceholderPanel } from "./PlaceholderPanel";
import { toast } from "../ui/Toast";

type ApiCardProps = {
  value: ApiSchema;
  index: number;
  model: ChainModel;
  onChange: (next: ApiSchema) => void;
  onDelete: () => void;
};

const inputCls = "w-full rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";
const labelCls = "mb-0.5 block text-[8px] text-[var(--color-muted)]";

export function ApiCard({ value, index, model, onChange, onDelete }: ApiCardProps) {
  const [open, setOpen] = useState(true);
  const a = value;
  const urlRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  function patch(p: Partial<ApiSchema>) {
    onChange({ ...a, ...p });
  }

  function insertPh(target: "url" | "body", code: string) {
    if (target === "url") {
      const el = urlRef.current;
      if (!el) return;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? el.value.length;
      const next = el.value.slice(0, start) + code + el.value.slice(end);
      patch({ url: next });
      requestAnimationFrame(() => {
        el.focus();
        const pos = start + code.length;
        el.setSelectionRange(pos, pos);
      });
    } else {
      const el = bodyRef.current;
      if (!el) return;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? el.value.length;
      const next = el.value.slice(0, start) + code + el.value.slice(end);
      // body 文本框存的是 JSON 字符串，占位符插入后保持字符串
      patch({ body: next });
      requestAnimationFrame(() => {
        el.focus();
        const pos = start + code.length;
        el.setSelectionRange(pos, pos);
      });
    }
  }

  /** 在 KeyValueEditor 行的值末尾追加占位符 */
  function appendPhToValue(field: "headers" | "query", key: string, current: string, code: string) {
    const next = { ...(a[field] || {}), [key]: current + code };
    patch({ [field]: next } as Partial<ApiSchema>);
  }

  // body 显示为 JSON 字符串
  const bodyText = a.body != null ? (typeof a.body === "string" ? a.body : JSON.stringify(a.body, null, 2)) : "";

  function setBodyText(text: string) {
    const v = text.trim();
    if (!v) {
      patch({ body: null });
      return;
    }
    try {
      patch({ body: JSON.parse(v) });
    } catch {
      // 允许占位符导致非严格 JSON，保留原始字符串
      patch({ body: text });
    }
  }

  // JSON 整理：a.body 已是对象（setBodyText 输入时 JSON.parse 存成对象），
  // 整理只需重新 stringify 显示，无需从文本重新 parse。
  // 若 a.body 是字符串（历史数据/占位符导致 parse 失败保留的），尝试解析为对象。
  function formatBody() {
    if (a.body == null) return;
    if (typeof a.body === "string") {
      // 字符串形态：尝试解析为对象（占位符 {{...}} 替换为哨兵再还原）
      const sentinels: { sentinel: string; original: string }[] = [];
      let idx = 0;
      const withSentinels = a.body.replace(/\{\{[^{}]*\}\}/g, (m, offset, str) => {
        const quoted = str[offset - 1] === '"';
        const sentinel = `__PH_${idx}__`;
        sentinels.push({ sentinel, original: m });
        idx += 1;
        return quoted ? sentinel : `"${sentinel}"`;
      });
      let parsed: unknown;
      try {
        parsed = JSON.parse(withSentinels);
      } catch {
        toast("error", "body 不是合法 JSON，无法整理");
        return;
      }
      function revive(o: unknown): unknown {
        if (typeof o === "string") {
          const hit = sentinels.find((s) => o === s.sentinel);
          return hit ? hit.original : o;
        }
        if (Array.isArray(o)) return o.map(revive);
        if (o && typeof o === "object") {
          const out: Record<string, unknown> = {};
          for (const [k, v] of Object.entries(o as Record<string, unknown>)) out[k] = revive(v);
          return out;
        }
        return o;
      }
      patch({ body: revive(parsed) as Record<string, unknown> });
    }
    // 对象形态：直接 patch 自身（触发 bodyText 重新 stringify 显示缩进 JSON）
    else {
      patch({ body: { ...(a.body as Record<string, unknown>) } });
    }
    toast("success", "body 已整理");
  }

  return (
    <div className="rounded-[var(--radius-form)] border border-[var(--color-border)] bg-white">
      <div
        className="flex cursor-pointer items-center gap-2 px-3 py-2"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown className="h-4 w-4 text-[var(--color-muted)]" /> : <ChevronRight className="h-4 w-4 text-[var(--color-muted)]" />}
        <span className="rounded-full bg-[var(--color-surface-alt)] px-2 py-0.5 text-[8px] font-semibold text-[var(--color-body)]">
          API {index + 1}
        </span>
        <input
          value={a.id}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => patch({ id: e.target.value })}
          placeholder="id(唯一)"
          className="w-32 rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-0.5 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]"
        />
        <input
          value={a.name ?? ""}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => patch({ name: e.target.value })}
          placeholder="名称(可选)"
          className="flex-1 rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-0.5 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]"
        />
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2 py-0.5 text-[11px] text-[var(--color-error)] hover:bg-[var(--color-hover)] cursor-pointer"
        >
          <Trash2 className="h-3 w-3" /> 删除
        </button>
      </div>

      {open && (
        <div className="space-y-3 border-t border-[var(--color-border)] p-3">
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className={labelCls}>method</label>
              <select
                value={a.method}
                onChange={(e) => patch({ method: e.target.value as ApiSchema["method"] })}
                className={inputCls}
              >
                {HTTP_METHODS.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            <div className="col-span-2">
              <label className={labelCls}>url（可含占位符）</label>
              <div className="flex items-center gap-1.5">
                <input
                  ref={urlRef}
                  value={a.url}
                  onChange={(e) => patch({ url: e.target.value })}
                  placeholder="http://host/orders/{{order_no}}/detail"
                  className={cn(inputCls, "flex-1")}
                />
                <PlaceholderPanel model={model} onInsert={(c) => insertPh("url", c)} />
              </div>
            </div>
          </div>

          <div>
            <label className={labelCls}>headers</label>
            <KeyValueEditor
              value={a.headers || {}}
              onChange={(headers) => patch({ headers })}
              renderValueExtra={(_k, v) => (
                <PlaceholderPanel model={model} onInsert={(c) => appendPhToValue("headers", _k, v, c)} />
              )}
            />
          </div>

          <div>
            <label className={labelCls}>query</label>
            <KeyValueEditor
              value={a.query || {}}
              onChange={(query) => patch({ query })}
              renderValueExtra={(_k, v) => (
                <PlaceholderPanel model={model} onInsert={(c) => appendPhToValue("query", _k, v, c)} />
              )}
            />
          </div>

          <div>
            <div className="flex items-center gap-2">
              <label className={labelCls}>body（可含占位符）</label>
              <select
                value={a.body_type || "json"}
                onChange={(e) => patch({ body_type: e.target.value as "json" | "form" })}
                className="rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-1.5 py-0.5 text-[8px] text-[var(--color-body)]"
              >
                <option value="json">JSON</option>
                <option value="form">表单 (urlencoded)</option>
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <AutoResizeTextarea
                ref={bodyRef}
                value={bodyText}
                onChange={(e) => setBodyText(e.target.value)}
                placeholder={a.body_type === "form" ? '{"session_id": "{{steps.s1.sid}}", "message": "hi"}' : '{"user_id": "{{user_id}}"}'}
                className={cn(inputCls, "flex-1 font-mono")}
              />
              <div className="flex shrink-0 flex-col gap-1">
                {a.body_type !== "form" && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      formatBody();
                    }}
                    className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-1.5 py-0.5 text-[8px] font-semibold text-[var(--color-body)] hover:bg-[var(--color-hover)] cursor-pointer"
                    title="把 body 格式化为缩进 JSON（兼容占位符）"
                  >
                    <AlignLeft className="h-3 w-3" /> 整理
                  </button>
                )}
                <PlaceholderPanel model={model} onInsert={(c) => insertPh("body", c)} />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className={labelCls}>timeout(秒)</label>
              <input
                type="number"
                value={a.timeout}
                onChange={(e) => patch({ timeout: +e.target.value || 0 })}
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls}>on_error</label>
              <select
                value={a.on_error}
                onChange={(e) => patch({ on_error: e.target.value as ApiSchema["on_error"] })}
                className={inputCls}
              >
                <option value="abort">abort</option>
                <option value="continue">continue</option>
                <option value="retry">retry</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>retry 次数</label>
              <input
                type="number"
                value={a.retry}
                onChange={(e) => patch({ retry: +e.target.value || 0 })}
                className={inputCls}
              />
            </div>
          </div>

          <div>
            <label className={labelCls}>extract 输出提取（输出名 → JSONPath）</label>
            <KeyValueEditor
              value={a.extract || {}}
              onChange={(extract) => patch({ extract })}
              keyPlaceholder="输出名"
              valuePlaceholder="JSONPath，如 data.orderNo 或 list[0].id"
            />
          </div>

          <div>
            <label className={labelCls}>extract_to_result 回写结果（字段名 → JSONPath，如 node_id / trace_no）</label>
            <KeyValueEditor
              value={a.extract_to_result || {}}
              onChange={(extract_to_result) => patch({ extract_to_result })}
              keyPlaceholder="结果字段名，如 node_id 或 trace_no"
              valuePlaceholder="JSONPath，如 data.nodeId 或 data.traceNo"
            />
          </div>

          <div>
            <label className={labelCls}>认证</label>
            <AuthEditor value={ensureAuth(a)} onChange={(auth) => patch({ auth })} />
          </div>
        </div>
      )}
    </div>
  );
}

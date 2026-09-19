// 裁判模型认证方式编辑器（受控组件）。
// 仅两种：static（用上方「API 密钥」，无额外字段）/ dynamic（可折叠面板配置取 token 的接口）。
// 值类型 AuthConfig；dynamic 时 token_api 子表单承载接口配置。
import { useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "../../lib/utils";
import { HTTP_METHODS, defaultTokenApi, type AuthConfig, type TokenApiConfig } from "./types";
import { KeyValueEditor } from "./KeyValueEditor";
import { configs } from "../../lib/api";
import { ApiError } from "../../lib/http";

type LlmAuthEditorProps = {
  value: AuthConfig;
  onChange: (next: AuthConfig) => void;
  disabled?: boolean;
  /** 刷新成功后回调（用于刷新父组件的 configs 缓存，使 API 密钥行自动更新）。 */
  onRefreshed?: () => void;
};

const inputCls = "w-full rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";
const labelCls = "mb-0.5 block text-[10px] text-[var(--color-muted)]";

export function LlmAuthEditor({ value, onChange, disabled, onRefreshed }: LlmAuthEditorProps) {
  const auth = value;
  const isDynamic = auth.type === "dynamic";
  const [open, setOpen] = useState(isDynamic);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState<{
    ok: boolean;
    message: string;
    token_preview?: string;
    cache_ttl?: number;
    at: string;
  } | null>(null);

  /** 手动刷新动态 token：强制绕过缓存调 token 接口，验证链路是否生效。
   *  传当前表单草稿，让用户保存前即可验证配置。结果在面板内联展示。 */
  async function refreshToken() {
    setRefreshing(true);
    setRefreshResult(null);
    try {
      const res = await configs.refreshLlmToken(auth as unknown as Record<string, unknown>);
      setRefreshResult({ ok: true, message: res.message, token_preview: res.token_preview, cache_ttl: res.cache_ttl, at: new Date().toLocaleTimeString() });
      onRefreshed?.();
    } catch (e) {
      setRefreshResult({ ok: false, message: e instanceof ApiError ? e.message : "刷新 token 失败", at: new Date().toLocaleTimeString() });
    } finally {
      setRefreshing(false);
    }
  }

  function setType(type: AuthConfig["type"]) {
    if (type === "dynamic") {
      onChange({ ...auth, type, token_api: auth.token_api ?? defaultTokenApi() });
      setOpen(true);
    } else {
      onChange({ ...auth, type });
    }
  }

  function patchToken(t: Partial<TokenApiConfig>) {
    const base = auth.token_api ?? defaultTokenApi();
    onChange({ ...auth, token_api: { ...base, ...t } });
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)_auto] items-center gap-4">
        <div>
          <div className="text-[11px] text-[var(--color-title)]">认证方式</div>
        </div>
        <select
          value={auth.type}
          disabled={disabled}
          onChange={(e) => setType(e.target.value as AuthConfig["type"])}
          className={inputCls}
        >
          <option value="static">静态（使用 API 密钥）</option>
          <option value="dynamic">动态（接口获取 token）</option>
        </select>
        <div className="w-24 text-right">
          {disabled && <span className="text-[11px] text-[var(--color-muted)]">只读</span>}
        </div>
      </div>

      {isDynamic && (
        <div className="md:pl-[220px]">
          <div className="rounded-[var(--radius-form)] border border-[var(--color-border)] bg-[var(--color-surface-alt)]">
            <div className="flex items-center">
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="flex flex-1 items-center gap-1.5 px-3 py-2 cursor-pointer"
              >
                {open ? <ChevronDown className="h-3.5 w-3.5 text-[var(--color-muted)]" /> : <ChevronRight className="h-3.5 w-3.5 text-[var(--color-muted)]" />}
                <span className="text-[11px] font-medium text-[var(--color-title)]">动态 token 接口</span>
              </button>
              <button
                type="button"
                onClick={refreshToken}
                disabled={disabled || refreshing}
                className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2 py-1 text-[11px] text-[var(--color-body)] hover:bg-[var(--color-hover)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                title="强制绕过缓存调 token 接口，验证取 token 是否生效（以当前表单配置为准）"
              >
                <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} />
                {refreshing ? "刷新中…" : "手动刷新"}
              </button>
            </div>
            {refreshResult && (
              <div className={cn(
                "flex items-center gap-2 px-3 py-2 text-[11px] border-t",
                refreshResult.ok
                  ? "border-[var(--color-border)] bg-emerald-50 text-emerald-700"
                  : "border-[var(--color-border)] bg-red-50 text-red-700"
              )}>
                {refreshResult.ok
                  ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                  : <XCircle className="h-3.5 w-3.5 shrink-0" />}
                <span className="flex-1 min-w-0 break-all">{refreshResult.message}</span>
                {refreshResult.ok && refreshResult.token_preview && (
                  <span className="font-mono text-[10px] shrink-0">token: {refreshResult.token_preview}</span>
                )}
                {refreshResult.ok && refreshResult.cache_ttl != null && (
                  <span className="text-[10px] shrink-0">缓存 {refreshResult.cache_ttl}s</span>
                )}
                <span className="text-[10px] text-[var(--color-muted)] shrink-0">{refreshResult.at}</span>
              </div>
            )}

            {open && auth.token_api && (
              <div className="space-y-2 border-t border-[var(--color-border)] p-3">
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className={labelCls}>method</label>
                  <select
                    value={auth.token_api.method}
                    disabled={disabled}
                    onChange={(e) => patchToken({ method: e.target.value as TokenApiConfig["method"] })}
                    className={inputCls}
                  >
                    {HTTP_METHODS.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <div className="col-span-2">
                  <label className={labelCls}>url</label>
                  <input
                    value={auth.token_api.url}
                    disabled={disabled}
                    onChange={(e) => patchToken({ url: e.target.value })}
                    placeholder="http://host/token"
                    className={inputCls}
                  />
                </div>
              </div>
              <div>
                <label className={labelCls}>headers</label>
                <KeyValueEditor
                  value={auth.token_api.headers || {}}
                  onChange={(headers) => patchToken({ headers })}
                />
              </div>
              <div>
                <label className={labelCls}>query</label>
                <KeyValueEditor
                  value={auth.token_api.query || {}}
                  onChange={(query) => patchToken({ query })}
                />
              </div>
              <div>
                <label className={labelCls}>body（JSON）</label>
                <textarea
                  value={auth.token_api.body != null ? (typeof auth.token_api.body === "string" ? auth.token_api.body : JSON.stringify(auth.token_api.body)) : ""}
                  disabled={disabled}
                  onChange={(e) => {
                    const v = e.target.value.trim();
                    let parsed: unknown = null;
                    if (v) {
                      try {
                        parsed = JSON.parse(v);
                      } catch {
                        parsed = v;
                      }
                    }
                    patchToken({ body: parsed });
                  }}
                  rows={2}
                  className={cn(inputCls, "resize-y font-mono")}
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className={labelCls}>extract（JSONPath，取 token）</label>
                  <input
                    value={auth.token_api.extract}
                    disabled={disabled}
                    onChange={(e) => patchToken({ extract: e.target.value })}
                    placeholder="$.access_token"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>ttl（秒，token 寿命）</label>
                  <input
                    type="number"
                    min={1}
                    value={auth.token_api.ttl}
                    disabled={disabled}
                    onChange={(e) => patchToken({ ttl: +e.target.value || 0 })}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>timeout（秒）</label>
                  <input
                    type="number"
                    min={1}
                    value={auth.token_api.timeout}
                    disabled={disabled}
                    onChange={(e) => patchToken({ timeout: +e.target.value || 0 })}
                    className={inputCls}
                  />
                </div>
              </div>
            </div>
          )}
          </div>
        </div>
      )}
    </div>
  );
}

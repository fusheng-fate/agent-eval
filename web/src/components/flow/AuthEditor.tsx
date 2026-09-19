// 认证编辑器：none / static / dynamic（token_api 子表单）。受控组件。
// 移植自 reference/legacy/page-src/.../apiChain/AuthEditor.tsx，按 DESIGN.md 重着色。
import { cn } from "../../lib/utils";
import { HTTP_METHODS, defaultTokenApi, type AuthConfig, type TokenApiConfig } from "./types";
import { KeyValueEditor } from "./KeyValueEditor";

type AuthEditorProps = {
  value: AuthConfig;
  onChange: (next: AuthConfig) => void;
};

const inputCls = "w-full rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";
const labelCls = "mb-0.5 block text-[8px] text-[var(--color-muted)]";

export function AuthEditor({ value, onChange }: AuthEditorProps) {
  const auth = value;

  function patch(p: Partial<AuthConfig>) {
    onChange({ ...auth, ...p });
  }

  function patchToken(t: Partial<TokenApiConfig>) {
    const base = auth.token_api ?? defaultTokenApi();
    onChange({ ...auth, token_api: { ...base, ...t } });
  }

  return (
    <div className="space-y-2">
      <div>
        <label className={labelCls}>认证方式</label>
        <select
          value={auth.type}
          onChange={(e) => {
            const type = e.target.value as AuthConfig["type"];
            if (type === "dynamic" && !auth.token_api) {
              patch({ type, token_api: defaultTokenApi() });
            } else {
              patch({ type });
            }
          }}
          className={inputCls}
        >
          <option value="none">none 无认证</option>
          <option value="static">static 静态 token</option>
          <option value="dynamic">dynamic 动态 token</option>
        </select>
      </div>

      {auth.type === "static" && (
        <div className="space-y-2">
          <div>
            <label className={labelCls}>static_token</label>
            <input
              value={auth.static_token ?? ""}
              onChange={(e) => patch({ static_token: e.target.value })}
              className={inputCls}
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className={labelCls}>token_in</label>
              <select
                value={auth.token_in}
                onChange={(e) => patch({ token_in: e.target.value as AuthConfig["token_in"] })}
                className={inputCls}
              >
                <option value="header">header</option>
                <option value="query">query</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>token_name</label>
              <input
                value={auth.token_name}
                onChange={(e) => patch({ token_name: e.target.value })}
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls}>token_prefix</label>
              <input
                value={auth.token_prefix}
                onChange={(e) => patch({ token_prefix: e.target.value })}
                placeholder="如 Bearer "
                className={inputCls}
              />
            </div>
          </div>
        </div>
      )}

      {auth.type === "dynamic" && (
        <>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className={labelCls}>token_in</label>
              <select
                value={auth.token_in}
                onChange={(e) => patch({ token_in: e.target.value as AuthConfig["token_in"] })}
                className={inputCls}
              >
                <option value="header">header</option>
                <option value="query">query</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>token_name</label>
              <input
                value={auth.token_name}
                onChange={(e) => patch({ token_name: e.target.value })}
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls}>token_prefix</label>
              <input
                value={auth.token_prefix}
                onChange={(e) => patch({ token_prefix: e.target.value })}
                placeholder="如 Bearer "
                className={inputCls}
              />
            </div>
          </div>

          {auth.token_api && (
            <div className="space-y-2 rounded-[var(--radius-form)] border border-[var(--color-border)] bg-[var(--color-surface-alt)] p-2">
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className={labelCls}>token 接口 method</label>
                  <select
                    value={auth.token_api.method}
                    onChange={(e) => patchToken({ method: e.target.value as TokenApiConfig["method"] })}
                    className={inputCls}
                  >
                    {HTTP_METHODS.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <div className="col-span-2">
                  <label className={labelCls}>token 接口 url</label>
                  <input
                    value={auth.token_api.url}
                    onChange={(e) => patchToken({ url: e.target.value })}
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
                <label className={labelCls}>body(JSON)</label>
                <textarea
                  value={auth.token_api.body != null ? JSON.stringify(auth.token_api.body) : ""}
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
                  <label className={labelCls}>extract(JSONPath)</label>
                  <input
                    value={auth.token_api.extract}
                    onChange={(e) => patchToken({ extract: e.target.value })}
                    placeholder="$.access_token"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>ttl(秒)</label>
                  <input
                    type="number"
                    value={auth.token_api.ttl}
                    onChange={(e) => patchToken({ ttl: +e.target.value || 0 })}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>timeout(秒)</label>
                  <input
                    type="number"
                    value={auth.token_api.timeout}
                    onChange={(e) => patchToken({ timeout: +e.target.value || 0 })}
                    className={inputCls}
                  />
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {auth.type === "none" && (
        <div className="text-[8px] text-[var(--color-muted)]">无认证</div>
      )}
    </div>
  );
}

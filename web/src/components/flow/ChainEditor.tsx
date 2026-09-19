// 链路编排编辑器（受控组件）。
// 移植自 reference/legacy/page-src/.../apiChain/ChainEditor.tsx，按 DESIGN.md 重着色。
// 负责编辑 name / fail_fast / variables / apis / steps；保存由父容器（模板对话框）统一触发。
import { useEffect, useRef, useState } from "react";
import { Plus, FileUp, Sparkles, KeyRound, Copy } from "lucide-react";
import { cn } from "../../lib/utils";
import { newApi, newStep, type ChainModel, type PreApi, type PreApiGroup } from "./types";
import { ApiCard } from "./ApiCard";
import { AutoResizeTextarea } from "./AutoResizeTextarea";
import { StepCard } from "./StepCard";
import { toast } from "../ui/Toast";
import { KeyValueEditor } from "./KeyValueEditor";
import { PlaceholderPanel } from "./PlaceholderPanel";
import { FinalExtractEditor } from "./FinalExtractEditor";

type ChainEditorProps = {
  model: ChainModel;
  onChange: (next: ChainModel) => void;
};

const inputCls = "w-full rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";
const labelCls = "mb-0.5 block text-[8px] text-[var(--color-muted)]";

/** 内置示例链路：查用户 → 建订单 → 查详情 → 大模型客服。 */
const SAMPLE: ChainModel = {
  name: "智能客服下单链路:查用户 → 建订单 → 查详情 → 大模型客服",
  variables: { 用户名: "alice", 金额: "500", 指令: "帮我下单 500 元" },
  apis: [
    {
      id: "get_user",
      name: "按用户名查用户",
      method: "GET",
      url: "http://127.0.0.1:9001/users",
      query: { username: "{{vars.用户名}}" },
      timeout: 30,
      extract: { user_id: "$.data.user_id", user_name: "$.data.name", level: "$.data.level" },
      on_error: "abort",
      retry: 0,
    },
    {
      id: "create_order",
      name: "创建订单",
      method: "POST",
      url: "http://127.0.0.1:9001/orders",
      headers: { "Content-Type": "application/json" },
      body: { user_id: "{{user_id}}", amount: "{{vars.金额}}" },
      timeout: 30,
      extract: { order_no: "$.data.order_no" },
      on_error: "abort",
      retry: 0,
    },
    {
      id: "order_detail",
      name: "查订单详情",
      method: "GET",
      url: "http://127.0.0.1:9001/orders/{{order_no}}/detail",
      timeout: 30,
      extract: { status: "$.data.status", item_qty: "$.data.items[0].qty" },
      on_error: "abort",
      retry: 0,
    },
    {
      id: "assistant_chat",
      name: "大模型客服（自然语言回复）",
      method: "POST",
      url: "http://127.0.0.1:9001/assistant/chat",
      headers: { "Content-Type": "application/json" },
      body: {
        message: "{{vars.指令}}",
        username: "{{vars.用户名}}",
        user_id: "{{user_id}}",
        context: { order_no: "{{order_no}}", amount: "{{vars.金额}}" },
      },
      timeout: 60,
      extract: { reply: "$.data.reply", model: "$.data.model" },
      on_error: "abort",
      retry: 1,
    },
  ],
  steps: [
    { id: "s1", api_id: "get_user" },
    { id: "s2", api_id: "create_order", inputs: { user_id: "{{steps.s1.user_id}}" } },
    { id: "s3", api_id: "order_detail", inputs: { order_no: "{{steps.s2.order_no}}" } },
    {
      id: "s4",
      api_id: "assistant_chat",
      inputs: { user_id: "{{steps.s1.user_id}}", order_no: "{{steps.s2.order_no}}" },
    },
  ],
  fail_fast: true,
  final_extract: {
    user_name: { step: 0, path: "data.name" },
    order_no: { step: 1, path: "data.order_no" },
    reply: { step: 3, path: "data.reply" },
  },
};

export function ChainEditor({ model, onChange }: ChainEditorProps) {
  const importRef = useRef<HTMLInputElement>(null);

  function patch(p: Partial<ChainModel>) {
    onChange({ ...model, ...p });
  }

  function patchApi(i: number, api: ChainModel["apis"][number]) {
    const apis = model.apis.slice();
    apis[i] = api;
    patch({ apis });
  }

  function addApi() {
    const n = model.apis.length + 1;
    patch({ apis: [...model.apis, newApi(n)] });
  }

  function deleteApi(i: number) {
    patch({ apis: model.apis.filter((_, idx) => idx !== i) });
  }

  function patchStep(i: number, step: ChainModel["steps"][number]) {
    const steps = model.steps.slice();
    steps[i] = step;
    patch({ steps });
  }

  function addStep() {
    const n = model.steps.length + 1;
    patch({ steps: [...model.steps, newStep(n, model.apis[0]?.id ?? "")] });
  }

  function deleteStep(i: number) {
    patch({ steps: model.steps.filter((_, idx) => idx !== i) });
  }

  function moveStep(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= model.steps.length) return;
    const steps = model.steps.slice();
    ;[steps[i], steps[j]] = [steps[j], steps[i]];
    patch({ steps });
  }

  function loadSample() {
    onChange(JSON.parse(JSON.stringify(SAMPLE)) as ChainModel);
  }

  function onImportChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as ChainModel;
        onChange({
          name: parsed.name ?? "",
          variables: parsed.variables ?? {},
          apis: parsed.apis ?? [],
          steps: parsed.steps ?? [],
          fail_fast: parsed.fail_fast !== false,
          final_extract: parsed.final_extract,
        });
      } catch (err) {
        toast("error", "JSON 解析失败：" + (err instanceof Error ? err.message : String(err)));
      }
    };
    reader.readAsText(file);
  }

  return (
    <div className="space-y-4">
      {/* 顶部操作（载入示例 + 导入 JSON） */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={loadSample}
          className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2.5 py-1 text-[11px] font-semibold text-[var(--brand)] hover:bg-[var(--color-hover)] cursor-pointer"
        >
          <Sparkles className="h-3.5 w-3.5" /> 载入示例
        </button>
        {/* 用 <label> 包裹隐藏 input：点击 label 由浏览器原生触发文件选择框 */}
        <label
          className="flex cursor-pointer items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2.5 py-1 text-[11px] font-semibold text-[var(--brand)] hover:bg-[var(--color-hover)]"
        >
          <input
            ref={importRef}
            type="file"
            accept=".json,application/json"
            onChange={onImportChange}
            style={{
              position: "absolute",
              width: 1,
              height: 1,
              padding: 0,
              margin: -1,
              overflow: "hidden",
              clip: "rect(0,0,0,0)",
              whiteSpace: "nowrap",
              border: 0,
            }}
          />
          <FileUp className="h-3.5 w-3.5" /> 导入 JSON 文件
        </label>
      </div>

      {/* 名称 + fail_fast */}
      <div className="grid grid-cols-3 gap-2">
        <div className="col-span-2">
          <label className={labelCls}>链路名称</label>
          <input
            value={model.name}
            onChange={(e) => patch({ name: e.target.value })}
            placeholder="anonymous-chain"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>fail_fast（遇 abort 立即停止）</label>
          <select
            value={String(model.fail_fast)}
            onChange={(e) => patch({ fail_fast: e.target.value === "true" })}
            className={inputCls}
          >
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </div>
      </div>

      {/* 全局变量 */}
      <div className="rounded-[var(--radius-form)] border border-[var(--color-border)] bg-white p-3">
        <div className="mb-2 text-[11px] font-bold text-[var(--color-title)]">全局变量</div>
        <KeyValueEditor
          value={model.variables}
          onChange={(variables) => patch({ variables })}
          keyPlaceholder="变量名（Excel 表头列即变量名）"
          valuePlaceholder="默认值"
        />
      </div>

      {/* 前置 API + 变量组 */}
      <PreApiEditor
        preApi={model.pre_api}
        preApiGroups={model.pre_api_groups}
        model={model}
        onChange={(pre_api, pre_api_groups) => patch({ pre_api, pre_api_groups })}
      />

      {/* API 列表 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-bold text-[var(--color-title)]">API 定义（{model.apis.length}）</div>
          <button
            type="button"
            onClick={addApi}
            className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2.5 py-1 text-[11px] font-semibold text-[var(--brand)] hover:bg-[var(--color-hover)] cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" /> 添加 API
          </button>
        </div>
        {model.apis.length === 0 ? (
          <div className={cn("rounded-[var(--radius-form)] border border-dashed border-[var(--input-border)] p-4 text-center text-[11px] text-[var(--color-muted)]")}>
            暂无 API，点击「添加 API」或「载入示例」
          </div>
        ) : (
          model.apis.map((a, i) => (
            <ApiCard
              key={i}
              value={a}
              index={i}
              model={model}
              onChange={(next) => patchApi(i, next)}
              onDelete={() => deleteApi(i)}
            />
          ))
        )}
      </div>

      {/* 步骤列表 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-bold text-[var(--color-title)]">执行步骤（{model.steps.length}）</div>
          <button
            type="button"
            onClick={addStep}
            className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2.5 py-1 text-[11px] font-semibold text-[var(--brand)] hover:bg-[var(--color-hover)] cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" /> 添加步骤
          </button>
        </div>
        {model.steps.length === 0 ? (
          <div className="rounded-[var(--radius-form)] border border-dashed border-[var(--input-border)] p-4 text-center text-[11px] text-[var(--color-muted)]">
            暂无步骤，点击「添加步骤」
          </div>
        ) : (
          model.steps.map((s, i) => (
            <StepCard
              key={i}
              value={s}
              index={i}
              total={model.steps.length}
              apis={model.apis}
              onChange={(next) => patchStep(i, next)}
              onDelete={() => deleteStep(i)}
              onMove={(dir) => moveStep(i, dir)}
            />
          ))
        )}
      </div>

      {/* 最终输出提取（final_extract，跨步骤多字段） */}
      <FinalExtractEditor
        value={model.final_extract}
        steps={model.steps}
        apis={model.apis}
        onChange={(final_extract) => patch({ final_extract })}
      />
    </div>
  );
}

// ---------- 前置 API + 变量组编辑器 ----------

const preApiInputCls = "w-full rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1 text-xs text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]";
const preApiLabelCls = "mb-0.5 block text-[10px] text-[var(--color-muted)]";

function PreApiEditor({
  preApi,
  preApiGroups,
  model,
  onChange,
}: {
  preApi: PreApi | undefined;
  preApiGroups: PreApiGroup[] | undefined;
  model: ChainModel;
  onChange: (preApi: PreApi | undefined, preApiGroups: PreApiGroup[] | undefined) => void;
}) {
  // 启用开关：仅 preApi.enabled === true 才真正执行（v1.5）。缺省视为未启用。
  const enabled = preApi?.enabled === true;
  const [open, setOpen] = useState(enabled || (preApiGroups && preApiGroups.length > 0));
  // Body（json 形态）本地受控文本：始终存原始字符串（含 {{占位符}}），
  // 避免「value 从对象派生 + JSON.parse 失败即忽略」导致含占位符的 body 无法输入/保存。
  const [bodyText, setBodyText] = useState(() =>
    preApi?.body_type === "form" ? "" : preApi?.body != null ? (typeof preApi.body === "string" ? preApi.body : JSON.stringify(preApi.body, null, 2)) : "",
  );
  // 数据晚到（useQuery 异步填充 model）时同步本地受控文本与展开态，
  // 否则 bodyText/open 停留在挂载期的空值，导致后端有数据但前端 Body 渲染为空 / 面板收起。
  const bodySig = preApi?.body_type === "form" ? "" : preApi?.body != null ? (typeof preApi.body === "string" ? preApi.body : JSON.stringify(preApi.body, null, 2)) : "";
  useEffect(() => {
    setBodyText(bodySig);
  }, [bodySig]);
  useEffect(() => {
    if (enabled) setOpen(true);
  }, [enabled]);
  function patchPreApi(p: Partial<PreApi>) {
    onChange({ method: "POST", url: "", timeout: 60, retry: 3, ...preApi, enabled: true, ...p }, preApiGroups);
  }

  /** 勾选/取消「启用前置 API」：启用时保留已填内容，取消时不写 pre_api（后端即视为未配置） */
  function toggleEnabled(next: boolean) {
    if (next) {
      onChange({ method: "POST", url: "", timeout: 60, retry: 3, ...preApi, enabled: true }, preApiGroups);
    } else {
      onChange(undefined, preApiGroups);
    }
  }

  /** 在 KeyValueEditor 行的值末尾追加占位符（headers/query 用） */
  function appendPhToValue(field: "headers" | "query", key: string, current: string, code: string) {
    const cur = (preApi?.[field] || {}) as Record<string, string>;
    patchPreApi({ [field]: { ...cur, [key]: current + code } } as Partial<PreApi>);
  }

  function patchGroup(i: number, g: PreApiGroup) {
    const groups = (preApiGroups || []).slice();
    groups[i] = g;
    onChange(preApi, groups);
  }

  function addGroup() {
    const groups = [...(preApiGroups || []), {}];
    onChange(preApi, groups);
  }

  function removeGroup(i: number) {
    const groups = (preApiGroups || []).filter((_, idx) => idx !== i);
    onChange(preApi, groups.length > 0 ? groups : undefined);
  }

  /** 复制第 i 组：深拷贝后追加到末尾，避免与原组共享引用 */
  function copyGroup(i: number) {
    const groups = [...(preApiGroups || [])];
    groups.push({ ...(groups[i] || {}) });
    onChange(preApi, groups);
  }

  return (
    <div className="rounded-[var(--radius-form)] border border-[var(--color-border)] bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2.5 cursor-pointer"
      >
        <span className="flex items-center gap-1.5 text-xs font-bold text-[var(--color-title)]">
          <KeyRound className="h-3.5 w-3.5 text-[var(--brand)]" />
          前置 API + 变量组
          {enabled ? (
            <span className="text-[10px] text-[var(--brand)] font-normal">（已启用）</span>
          ) : (
            <span className="text-[10px] text-[var(--color-muted)] font-normal">（未启用）</span>
          )}
        </span>
        <span className="text-xs text-[var(--color-muted)]">{open ? "收起" : "展开"}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-[var(--color-border)] p-3">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => toggleEnabled(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--brand)] cursor-pointer"
            />
            <span className="text-[11px] font-medium text-[var(--color-title)]">启用前置 API</span>
          </label>
          <p className="text-[11px] text-[var(--color-muted)]">
            {enabled
              ? "前置 API：每组开始前调一次，获取 session 等变量。变量组：循环分配给各轮次（第 N 轮用第 N%组数 组）。"
              : "未启用：不调用前置 API，变量组也不生效（后续用例仅引用全局变量）。勾选后才会执行。"}
          </p>

          {/* 前置 API 配置 */}
          <div className={cn(!enabled && "opacity-50 pointer-events-none select-none")} aria-disabled={!enabled}>
            <div className="mb-1.5 text-[11px] font-medium text-[var(--color-title)]">前置 API（获取 session）</div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className={preApiLabelCls}>Method</label>
                <select
                  value={preApi?.method || "POST"}
                  onChange={(e) => patchPreApi({ method: e.target.value as PreApi["method"] })}
                  className={preApiInputCls}
                >
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div className="col-span-2">
                <label className={preApiLabelCls}>URL</label>
                <input
                  value={preApi?.url || ""}
                  onChange={(e) => patchPreApi({ url: e.target.value })}
                  placeholder="https://target/session/create"
                  className={preApiInputCls}
                />
              </div>
            </div>
            <div className="mt-2 grid grid-cols-4 gap-2">
              <div>
                <label className={preApiLabelCls}>Body 类型</label>
                <select
                  value={preApi?.body_type || "json"}
                  onChange={(e) => patchPreApi({ body_type: e.target.value as "json" | "form" })}
                  className={preApiInputCls}
                >
                  <option value="json">JSON</option>
                  <option value="form">Form (urlencoded)</option>
                </select>
              </div>
              <div>
                <label className={preApiLabelCls}>Timeout（秒）</label>
                <input
                  type="number"
                  min={1}
                  value={preApi?.timeout ?? 60}
                  onChange={(e) => patchPreApi({ timeout: parseInt(e.target.value) || 60 })}
                  className={preApiInputCls}
                />
              </div>
              <div>
                <label className={preApiLabelCls}>Retry</label>
                <input
                  type="number"
                  min={0}
                  value={preApi?.retry ?? 3}
                  onChange={(e) => patchPreApi({ retry: parseInt(e.target.value) || 0 })}
                  className={preApiInputCls}
                />
              </div>
              <div>
                <label className={preApiLabelCls}>TTL（秒）</label>
                <input
                  type="number"
                  min={60}
                  value={preApi?.ttl_seconds ?? 3600}
                  onChange={(e) => patchPreApi({ ttl_seconds: parseInt(e.target.value) || 3600 })}
                  className={preApiInputCls}
                />
              </div>
            </div>
            <div className="mt-2">
              <label className={preApiLabelCls}>Headers</label>
              <KeyValueEditor
                value={preApi?.headers || {}}
                onChange={(headers) => patchPreApi({ headers: Object.keys(headers).length > 0 ? headers : undefined })}
                keyPlaceholder="Header 名（如 Authorization）"
                valuePlaceholder="值（如 Bearer {{token}}）"
                renderValueExtra={(_k, v) => (
                  <PlaceholderPanel model={model} onInsert={(c) => appendPhToValue("headers", _k, v, c)} />
                )}
              />
            </div>
            <div className="mt-2">
              <label className={preApiLabelCls}>Query</label>
              <KeyValueEditor
                value={preApi?.query || {}}
                onChange={(query) => patchPreApi({ query: Object.keys(query).length > 0 ? query : undefined })}
                keyPlaceholder="参数名"
                valuePlaceholder="值（支持占位符）"
                renderValueExtra={(_k, v) => (
                  <PlaceholderPanel model={model} onInsert={(c) => appendPhToValue("query", _k, v, c)} />
                )}
              />
            </div>
            <div className="mt-2">
              <label className={preApiLabelCls}>Body（支持 {"{{变量名}}"} 占位符）</label>
              {(preApi?.body_type || "json") === "form" ? (
                <KeyValueEditor
                  value={preApi?.body as Record<string, string> || {}}
                  onChange={(body) => patchPreApi({ body: Object.keys(body).length > 0 ? body : undefined })}
                  keyPlaceholder="字段名（如 phone）"
                  valuePlaceholder="值（如 {{phone}}）"
                />
              ) : (
                <AutoResizeTextarea
                  value={bodyText}
                  onChange={(e) => {
                    const v = e.target.value;
                    setBodyText(v);
                    // 始终存原始字符串（含占位符），后端执行时再渲染占位符 + json.loads
                    patchPreApi({ body: v.trim() ? v : undefined });
                  }}
                  placeholder='{"phone": "{{phone}}", "device": "{{device_id}}"}'
                  className={cn(preApiInputCls, "font-mono")}
                />
              )}
            </div>
            <div className="mt-2">
              <label className={preApiLabelCls}>Extract（从响应提取变量，JSONPath）</label>
              <KeyValueEditor
                value={preApi?.extract || {}}
                onChange={(extract) => patchPreApi({ extract: Object.keys(extract).length > 0 ? extract : undefined })}
                keyPlaceholder="变量名（如 session_id）"
                valuePlaceholder="JSONPath（如 data.sessionId）"
              />
            </div>
          </div>

          {/* 变量组 */}
          <div className={cn(!enabled && "opacity-50 pointer-events-none select-none")} aria-disabled={!enabled}>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[11px] font-medium text-[var(--color-title)]">
                变量组（循环分配给各轮次，共 {preApiGroups?.length || 0} 组）
              </span>
              <button
                type="button"
                onClick={addGroup}
                className="flex items-center gap-1 rounded-[var(--radius-form)] border border-[var(--input-border)] px-2 py-0.5 text-[11px] text-[var(--brand)] hover:bg-[var(--color-hover)] cursor-pointer"
              >
                <Plus className="h-3 w-3" /> 添加变量组
              </button>
            </div>
            {(preApiGroups || []).length === 0 ? (
              <div className="rounded-[var(--radius-form)] border border-dashed border-[var(--input-border)] p-3 text-center text-[11px] text-[var(--color-muted)]">
                暂无变量组。添加后，第 N 轮自动使用第 (N % 组数) 组的变量。
              </div>
            ) : (
              <div className="space-y-2">
                {(preApiGroups || []).map((g, i) => (
                  <div key={i} className="rounded-[var(--radius-form)] border border-[var(--color-border)] p-2">
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="text-[11px] font-medium text-[var(--color-title)]">组 {i + 1}</span>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => copyGroup(i)}
                          title="复制此变量组"
                          className="flex items-center gap-0.5 text-[11px] text-[var(--color-muted)] hover:text-[var(--brand)] hover:underline cursor-pointer"
                        >
                          <Copy className="h-3 w-3" /> 复制
                        </button>
                        <button
                          type="button"
                          onClick={() => removeGroup(i)}
                          className="text-[11px] text-[var(--color-error)] hover:underline cursor-pointer"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                    <KeyValueEditor
                      value={g}
                      onChange={(next) => patchGroup(i, next)}
                      keyPlaceholder="变量名（如 phone）"
                      valuePlaceholder="值（如 13800000001）"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

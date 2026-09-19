import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Plus, Pencil, Trash2, FilePlus2, FilePlus, X } from "lucide-react";
import { configs, flowTemplates, users } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { useAuth } from "../../context/AuthContext";
import type { ConfigOut, FlowTemplateOut, ParamPerm } from "../../lib/types";
import { cn } from "../../lib/utils";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Input, Select, Field } from "../../components/ui/Input";
import { Dialog } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Pagination } from "../../components/ui/Pagination";
import { toast } from "../../components/ui/Toast";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { ChainEditor } from "../../components/flow/ChainEditor";
import { LlmAuthEditor } from "../../components/flow/LlmAuthEditor";
import { defaultAuth, ensureAuth, type AuthConfig, type ChainModel } from "../../components/flow/types";

const TABS = ["裁判模型配置", "阈值", "流程模板", "用户管理"] as const;

function canEdit(cfg: ConfigOut, isAdmin: boolean): boolean {
  if (cfg.editable_by === "admin") return isAdmin;
  if (cfg.editable_by === "user") return true;
  return false;
}

function valueOf(cfg: ConfigOut): string {
  const v = cfg.config_value;
  if (v && typeof v === "object" && "value" in (v as Record<string, unknown>)) {
    return String((v as Record<string, unknown>).value ?? "");
  }
  return String(v ?? "");
}

export default function Configs() {
  const { isAdmin } = useAuth();
  const [searchParams] = useSearchParams();
  const tabs = (isAdmin ? TABS : TABS.filter((t) => t !== "用户管理")) as readonly string[];
  // 支持从任务中心「查看环境」跳入：?tab=流程模板&template=<id> 定位到流程模板页并打开对应模板
  const urlTab = searchParams.get("tab");
  const [tab, setTab] = useState<string>(
    urlTab && (TABS as readonly string[]).includes(urlTab) ? urlTab : "裁判模型配置"
  );
  const initialTemplate = searchParams.get("template") || "";

  return (
    <div className="space-y-6">
      <div className="flex gap-1 border-b border-[var(--color-border)] flex-wrap">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-2.5 text-[11px] border-b-2 -mb-px cursor-pointer",
              tab === t ? "border-[var(--brand)] text-[var(--brand)] font-medium" : "border-transparent text-[var(--color-body)]"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "流程模板" ? (
        <FlowTemplateManager isAdmin={isAdmin} initialTemplate={initialTemplate} />
      ) : tab === "用户管理" ? (
        isAdmin ? <UserManager /> : null
      ) : (
        <ConfigGroup tab={tab} isAdmin={isAdmin} />
      )}
    </div>
  );
}

const GROUP_PREFIX: Record<string, string> = {
  "裁判模型配置": "llm.",
  "阈值": "report.pass_threshold",
};

// 裁判模型配置页额外展示「模型并发上限」（全局配置 concurrency.model，与 LLM 配置同页保存）
const MODEL_CONCURRENCY_KEY = "concurrency.model";
// LLM 认证方式（JSON 配置，单独受控，不走字符串 draft）
const LLM_AUTH_KEY = "llm.auth";

/** 从 config_value 解析 AuthConfig（兼容 {value:{...}} 包装与裸对象）。
 *  仅关心 type 与 token_api；静态用 llm.api_key，无需 token_in/name/prefix。 */
function parseAuthValue(v: unknown): AuthConfig {
  const obj = (v && typeof v === "object" && "value" in (v as Record<string, unknown>))
    ? (v as Record<string, unknown>).value
    : v;
  const base = (obj && typeof obj === "object") ? (obj as Record<string, unknown>) : {};
  return {
    type: (base.type === "dynamic" ? "dynamic" : "static"),
    token_in: "header",
    token_name: "Authorization",
    token_prefix: "",
    token_api: base.token_api as AuthConfig["token_api"],
  };
}

function ConfigGroup({ tab, isAdmin }: { tab: string; isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data: all, isLoading } = useQuery({ queryKey: ["configs", "list"], queryFn: () => configs.list() });
  const prefix = GROUP_PREFIX[tab];
  // llm.auth 单独渲染（AuthEditor），不进字符串列表
  let items = (all || []).filter((c) =>
    (tab === "阈值" ? c.config_key === prefix : c.config_key.startsWith(prefix)) && c.config_key !== LLM_AUTH_KEY
  );
  if (tab === "裁判模型配置") {
    items = [...items, ...(all || []).filter((c) => c.config_key === MODEL_CONCURRENCY_KEY)];
  }
  const authItem = tab === "裁判模型配置" ? (all || []).find((c) => c.config_key === LLM_AUTH_KEY) : undefined;
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [authDraft, setAuthDraft] = useState<AuthConfig | null>(null);

  // 可编辑项：仅收集「可编辑且有改动」的 key，一次性批量保存
  const editableItems = items.filter((c) => canEdit(c, isAdmin));
  const dirtyKeys = editableItems.filter((c) => draft[c.config_key] !== undefined && draft[c.config_key] !== valueOf(c));
  const values: Record<string, unknown> = Object.fromEntries(dirtyKeys.map((c) => [c.config_key, draft[c.config_key]]));
  // llm.auth 改动检测 + 并入 values
  const authDirty = !!(authItem && authDraft && JSON.stringify(authDraft) !== JSON.stringify(parseAuthValue(authItem.config_value)));
  if (authDirty && authDraft) values[LLM_AUTH_KEY] = authDraft;

  const save = useMutation({
    mutationFn: () => configs.batchUpdate(values),
    onSuccess: (res) => {
      if (res.updated.length === 0) {
        toast("info", "无可保存的改动");
        return;
      }
      toast("success", `已保存 ${res.updated.length} 项`);
      qc.invalidateQueries({ queryKey: ["configs"] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "保存失败"),
  });

  if (isLoading) return <EmptyState title="加载中…" />;
  if (items.length === 0 && !authItem) return <EmptyState title="该分组暂无配置" />;

  const authEditable = authItem ? canEdit(authItem, isAdmin) : false;
  const authValue = authDraft ?? (authItem ? parseAuthValue(authItem.config_value) : defaultAuth());

  return (
    <Card
      title={tab}
      extra={
        <Button onClick={() => save.mutate()} disabled={(dirtyKeys.length === 0 && !authDirty) || save.isPending}>
          <Save size={16} /> 保存
        </Button>
      }
    >
      <div className="space-y-4">
        {(() => {
          // 认证方式插在 API 密钥行之后（先选类型，密钥再按类型生效）
          const apiKeyIdx = tab === "裁判模型配置" ? items.findIndex((c) => c.config_key === "llm.api_key") : -1;
          const before = apiKeyIdx >= 0 ? items.slice(0, apiKeyIdx) : items;
          const apiKey = apiKeyIdx >= 0 ? items[apiKeyIdx] : undefined;
          const after = apiKeyIdx >= 0 ? items.slice(apiKeyIdx + 1) : [];
          const row = (c: ConfigOut) => {
            const editable = canEdit(c, isAdmin);
            const cur = draft[c.config_key] ?? valueOf(c);
            return (
              <div key={c.config_key} className="grid grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)_auto] items-center gap-4">
                <div>
                  <div className="text-[11px] text-[var(--color-title)]">{c.description || c.config_key}</div>
                </div>
                <Input
                  value={cur}
                  disabled={!editable}
                  onChange={(e) => setDraft((d) => ({ ...d, [c.config_key]: e.target.value }))}
                  placeholder={editable ? "" : "不可编辑"}
                />
                <div className="w-24 text-right">
                  {!editable && <span className="text-[11px] text-[var(--color-muted)]">只读</span>}
                </div>
              </div>
            );
          };
          const authBlock = authItem && (
            <LlmAuthEditor
              value={authValue}
              onChange={(a) => setAuthDraft(a)}
              disabled={!authEditable}
              onRefreshed={() => {
                // 清掉 API 密钥的 draft 残留，让 refetch 后的新值生效
                setDraft((d) => { const { "llm.api_key": _, ...rest } = d; return rest; });
                qc.invalidateQueries({ queryKey: ["configs"] });
              }}
            />
          );
          return (
            <>
              {authBlock}
              {before.map(row)}
              {apiKey && row(apiKey)}
              {after.map(row)}
            </>
          );
        })()}
      </div>
    </Card>
  );
}

type CreateMode = { type: "blank" } | { type: "copy"; base: FlowTemplateOut };

function FlowTemplateManager({ isAdmin, initialTemplate }: { isAdmin: boolean; initialTemplate?: string }) {
  const qc = useQueryClient();
  const { data: list, isLoading } = useQuery({ queryKey: ["flowTemplates", "list"], queryFn: () => flowTemplates.list() });
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [createMode, setCreateMode] = useState<CreateMode | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [notified, setNotified] = useState(false);
  const [confirmDel, setConfirmDel] = useState<{ id: string; name: string } | null>(null);

  // 从任务中心「查看环境」跳入：列表加载后自动打开对应模板；模板已被删除则提示
  useEffect(() => {
    if (!initialTemplate || !list || notified) return;
    setNotified(true);
    if (list.some((t) => t.id === initialTemplate)) {
      setEditing(initialTemplate);
    } else {
      toast("info", "模板已被删除");
    }
  }, [initialTemplate, list, notified]);

  const del = useMutation({
    mutationFn: (id: string) => flowTemplates.remove(id),
    onSuccess: () => {
      toast("success", "已删除");
      qc.invalidateQueries({ queryKey: ["flowTemplates"] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "删除失败"),
  });

  const openCreate = (m: CreateMode) => {
    setCreateMode(m);
    setEditing("new");
    setShowCreate(false);
  };

  if (isLoading) return <EmptyState title="加载中…" />;

  return (
    <Card
      title="流程模板"
      extra={isAdmin ? <Button onClick={() => setShowCreate(true)}><Plus size={16} /> 新建</Button> : undefined}
    >
      {!list || list.length === 0 ? (
        <EmptyState title="暂无流程模板" />
      ) : (
        <div className="space-y-2">
          {list.map((t) => (
            <div key={t.id} className="flex items-center gap-3 border border-[var(--color-border)] rounded-[var(--radius-form)] px-4 py-3">
              <div className="flex-1">
                <div className="text-[11px] text-[var(--color-title)] font-medium">{t.name}</div>
                {t.description && <div className="text-[11px] text-[var(--color-muted)]">{t.description}</div>}
              </div>
              {isAdmin && (
                <div className="flex gap-1">
                  <button
                    onClick={() => openCreate({ type: "copy", base: t })}
                    className="text-[var(--color-muted)] hover:text-[var(--brand)] cursor-pointer"
                    title="基于此模板新建"
                  >
                    <FilePlus2 size={16} />
                  </button>
                  <button onClick={() => setEditing(t.id)} className="text-[var(--color-muted)] hover:text-[var(--brand)] cursor-pointer" title="编辑">
                    <Pencil size={16} />
                  </button>
                  <button
                    onClick={() => setConfirmDel({ id: t.id, name: t.name })}
                    className="text-[var(--color-muted)] hover:text-[var(--color-error)] cursor-pointer"
                    title="删除"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <CreateDialog open={showCreate} list={list || []} onPick={openCreate} onClose={() => setShowCreate(false)} />
      <TemplateDialog
        open={editing !== null}
        templateId={editing === "new" ? null : editing}
        baseTemplate={createMode?.type === "copy" ? createMode.base : undefined}
        onClose={() => setEditing(null)}
      />
      <ConfirmDialog
        open={!!confirmDel}
        title="确认删除"
        message={`确认删除流程模板「${confirmDel?.name}」？`}
        onConfirm={() => {
          if (confirmDel) del.mutate(confirmDel.id);
          setConfirmDel(null);
        }}
        onCancel={() => setConfirmDel(null)}
      />
    </Card>
  );
}

/** 新建方式选择：直接新建 / 基于已有模板复制 */
function CreateDialog({
  open,
  list,
  onPick,
  onClose,
}: {
  open: boolean;
  list: FlowTemplateOut[];
  onPick: (m: CreateMode) => void;
  onClose: () => void;
}) {
  const [baseId, setBaseId] = useState("");
  useEffect(() => {
    if (open) setBaseId("");
  }, [open]);

  return (
    <Dialog
      open={open}
      title="新建流程模板"
      onClose={onClose}
      widthClass="max-w-lg"
      footer={<Button variant="ghost" onClick={onClose}>取消</Button>}
    >
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => onPick({ type: "blank" })}
          className="w-full flex items-start gap-3 border border-[var(--color-border)] rounded-[var(--radius-form)] px-4 py-3 text-left hover:bg-[var(--color-hover)] cursor-pointer"
        >
          <FilePlus size={18} className="text-[var(--brand)] mt-0.5 shrink-0" />
          <div>
            <div className="text-[11px] text-[var(--color-title)] font-medium">直接新建</div>
            <div className="text-[11px] text-[var(--color-muted)] mt-0.5">从空白模板开始，自行编排测试流程</div>
          </div>
        </button>
        <div
          className={cn(
            "w-full flex items-start gap-3 border border-[var(--color-border)] rounded-[var(--radius-form)] px-4 py-3",
            list.length === 0 && "opacity-50"
          )}
        >
          <FilePlus2 size={18} className="text-[var(--brand)] mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="text-[11px] text-[var(--color-title)] font-medium">基于已有模板新建</div>
            <div className="text-[11px] text-[var(--color-muted)] mt-0.5 mb-2">
              {list.length === 0 ? "暂无可复制的模板" : "复制一个已有模板的内容，在其基础上修改"}
            </div>
            <Select
              value={baseId}
              disabled={list.length === 0}
              onChange={(e) => setBaseId(e.target.value)}
            >
              <option value="">选择模板…</option>
              {list.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </Select>
            <Button
              className="mt-3"
              disabled={!baseId}
              onClick={() => {
                const base = list.find((t) => t.id === baseId);
                if (base) onPick({ type: "copy", base });
              }}
            >
              复制并新建
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

/** 后端 chain_json → 编辑器 ChainModel（补齐 auth/on_error 等默认结构） */
function toModel(cj: unknown): ChainModel {
  const c = (cj || {}) as Record<string, any>;
  const apis: ChainModel["apis"] = (c.apis || []).map((a: any) => ({
    id: a.id ?? "",
    name: a.name ?? "",
    method: (a.method as any) || "GET",
    url: a.url ?? "",
    headers: a.headers || {},
    query: a.query || {},
    body: a.body ?? null,
    body_type: a.body_type ?? "json",
    auth: a.auth,
    timeout: a.timeout ?? 30,
    extract: a.extract || {},
    extract_to_result: a.extract_to_result || {},
    on_error: a.on_error ?? "abort",
    retry: a.retry ?? 0,
  }));
  const steps: ChainModel["steps"] = (c.steps || []).map((s: any) => ({
    id: s.id ?? "",
    api_id: s.api_id ?? "",
    inputs: s.inputs || {},
    optional: !!s.optional,
  }));
  return {
    name: c.name ?? "",
    variables: c.variables || {},
    apis,
    steps,
    fail_fast: c.fail_fast !== false,
    final_extract: c.final_extract,
    pre_api: c.pre_api,
    pre_api_groups: c.pre_api_groups,
  };
}

/** 编辑器 ChainModel → 后端 chain_json（保留 name/fail_fast/variables，apis 补齐 auth） */
function toChainJson(m: ChainModel): Record<string, unknown> {
  const apis = m.apis.map((a) => {
    const auth = ensureAuth(a);
    return {
      id: a.id,
      name: a.name || undefined,
      method: a.method,
      url: a.url,
      headers: a.headers || {},
      query: a.query || {},
      body: a.body ?? null,
      body_type: a.body_type,
      auth,
      timeout: a.timeout,
      extract: a.extract || {},
      extract_to_result: a.extract_to_result || {},
      on_error: a.on_error,
      retry: a.retry,
    };
  });
  return {
    name: m.name,
    variables: m.variables || {},
    apis,
    steps: m.steps.map((s) => ({ id: s.id, api_id: s.api_id, inputs: s.inputs || {}, optional: !!s.optional })),
    fail_fast: m.fail_fast,
    ...(m.final_extract !== undefined ? { final_extract: m.final_extract } : {}),
    ...(m.pre_api !== undefined ? { pre_api: m.pre_api } : {}),
    ...(m.pre_api_groups !== undefined && m.pre_api_groups.length > 0 ? { pre_api_groups: m.pre_api_groups } : {}),
  };
}

// ============================================================
// 参数开放（param_perms）— 按 paramPath 读写 chain_json 中的字段
// paramPath 形态：
//   vars.<名> / apis[i].<field>[.sub] / steps[i].inputs.<key>
//   pre_api.<field> / pre_api.<obj>.<key> / pre_api_groups[i].<k> / pre_api_groups.<k>（新增组）
// 字段的当前取值即「默认值」，在评估体系里作为预填值展示给用户。
// ============================================================
function getParamValue(m: ChainModel, path: string): unknown {
  const mm = m as unknown as Record<string, any>;
  if (path === "pre_api_groups") return mm.pre_api_groups;
  const am = path.match(/^(\w+)\[(\d+)\]\.(.+)$/);
  if (am) {
    const arr = mm[am[1]] || [];
    return arr[Number(am[2])]?.[am[3]];
  }
  const parts = path.split(".");
  if (parts[0] === "vars") return m.variables?.[parts[1]];
  if (parts[0] === "pre_api") {
    let cur: any = mm.pre_api;
    for (let i = 1; i < parts.length; i++) cur = cur?.[parts[i]];
    return cur;
  }
  if (parts[0] === "apis" || parts[0] === "steps") {
    const arr = mm[parts[0]] || [];
    let cur: any = arr[Number(parts[1])];
    for (let i = 2; i < parts.length; i++) cur = cur?.[parts[i]];
    return cur;
  }
  return undefined;
}

function patchParamValue(m: ChainModel, path: string, value: string): ChainModel {
  const parts = path.split(".");
  if (parts[0] === "vars") {
    const variables = { ...(m.variables || {}) };
    if (value === "") delete variables[parts[1]];
    else variables[parts[1]] = value;
    return { ...m, variables };
  }
  if (parts[0] === "apis") {
    const apis = m.apis.slice();
    const a: any = { ...apis[Number(parts[1])] };
    if (parts.length === 2) {
      // 整个字段（timeout 等）
      if (value === "") delete a[parts[1]];
      else a[parts[1]] = parts[1] === "timeout" || parts[1] === "retry" ? Number(value) : value;
    } else {
      // 嵌套字段（headers.X / query.X / body.X / auth.X …）
      const obj: any = { ...(a[parts[2]] ?? (parts[2] === "body" ? {} : {})) };
      if (value === "") delete obj[parts[3]];
      else obj[parts[3]] = value;
      a[parts[2]] = obj;
    }
    apis[Number(parts[1])] = a;
    return { ...m, apis };
  }
  if (parts[0] === "steps") {
    const steps = m.steps.slice();
    const s: any = { ...steps[Number(parts[1])] };
    const inputs: any = { ...(s.inputs || {}) };
    if (value === "") delete inputs[parts[3]];
    else inputs[parts[3]] = value;
    s.inputs = inputs;
    steps[Number(parts[1])] = s;
    return { ...m, steps };
  }
  if (parts[0] === "pre_api") {
    const pre: any = { ...(m.pre_api || {}) };
    if (parts.length === 2) {
      if (value === "") delete pre[parts[1]];
      else pre[parts[1]] = ["timeout", "retry", "ttl_seconds"].includes(parts[1]) ? Number(value) || 0 : value;
    } else {
      const obj: any = { ...(pre[parts[2]] ?? {}) };
      if (value === "") delete obj[parts[3]];
      else obj[parts[3]] = value;
      pre[parts[2]] = obj;
    }
    return { ...m, pre_api: pre };
  }
  return m;
}

/** 变量组参数（pre_api_groups[i].<k> / pre_api_groups.<k>）专用 patch：
 *  改值 / 删键（空值）/ 新增组（pre_api_groups 或 pre_api_groups.<k>）。
 *  删除组（整组移除）不在开放参数语义内，由模板编辑器的变量组区直接操作。 */
function patchGroupValue(m: ChainModel, path: string, value: string): ChainModel {
  const mm = m as unknown as Record<string, any>;
  const groups: Record<string, string>[] = (mm.pre_api_groups || []).slice();
  const am = path.match(/^pre_api_groups\[(\d+)\]\.(.+)$/);
  if (am) {
    const i = Number(am[1]);
    const g = { ...(groups[i] || {}) };
    if (value === "") delete g[am[2]];
    else g[am[2]] = value;
    groups[i] = g;
    return { ...m, pre_api_groups: groups };
  }
  if (path === "pre_api_groups") {
    let g: Record<string, string> | null = null;
    try { g = typeof value === "string" ? JSON.parse(value) : value; } catch { g = null; }
    if (g && typeof g === "object" && Object.keys(g).length > 0) {
      groups.push(Object.fromEntries(Object.entries(g).map(([k, v]) => [k, String(v)])));
    }
    return { ...m, pre_api_groups: groups };
  }
  const key = path.startsWith("pre_api_groups.") ? path.slice("pre_api_groups.".length) : "";
  if (key && value !== "") groups.push({ [key]: value });
  return { ...m, pre_api_groups: groups };
}

function paramPathLabel(path: string): string {
  if (path === "pre_api_groups") return "前置API · 变量组（全部）";
  const am = path.match(/^(\w+)\[(\d+)\]\.(.+)$/);
  if (am) {
    if (am[1] === "apis") return `API ${Number(am[2]) + 1} · ${am[3]}`;
    if (am[1] === "steps") return `步骤 ${Number(am[2]) + 1} · 入参 ${am[3]}`;
  }
  const parts = path.split(".");
  if (parts[0] === "vars") return `全局变量 ${parts[1]}`;
  if (parts[0] === "pre_api") return `前置API · ${parts.slice(1).join(".")}`;
  return path;
}

// 可开放的 API 顶层字段（整体开放）
const API_TOP_FIELDS = ["url", "timeout", "retry"] as const;
// 可开放的 API 嵌套字段（headers / query / body / auth）
const API_SUB_FIELDS = ["headers", "query", "body", "auth"] as const;
// 可开放的前置 API 顶层字段
const PRE_API_TOP_FIELDS = ["url", "method", "timeout", "retry", "ttl_seconds"] as const;
// 可开放的前置 API 嵌套字段
const PRE_API_SUB_FIELDS = ["headers", "query", "body", "extract"] as const;
// 变量组（开放后测试执行页展示全部变量组供修改/新增，见 v1.10）
const PRE_API_GROUPS_FIELD = "pre_api_groups";

/** 添加可开放参数：选字段类型 + 定位 + 子字段 → 构造 paramPath 回调 */
function AddParamPerm({ model, onAdd }: { model: ChainModel; onAdd: (paramPath: string) => void }) {
  const [kind, setKind] = useState<"vars" | "apis" | "steps" | "pre_api">("apis");
  const [idx, setIdx] = useState(0);
  const [field, setField] = useState<string>("url");
  const [sub, setSub] = useState("");

  const apis = model.apis;
  const steps = model.steps;
  const varNames = Object.keys(model.variables || {});
  const preApi = model.pre_api as Record<string, any> | undefined;

  // 当前选中的 API / 步骤
  const api = apis[idx];
  const step = steps[idx];
  const subKeys =
    kind === "apis" && api && API_SUB_FIELDS.includes(field as any)
      ? Object.keys((api as any)[field] || {})
      : kind === "steps" && step
        ? Object.keys(step.inputs || {})
        : kind === "pre_api" && preApi && PRE_API_SUB_FIELDS.includes(field as any)
          ? Object.keys(preApi[field] || {})
          : [];

  const buildPath = (): string => {
    if (kind === "vars") {
      const v = sub.trim();
      return v ? `vars.${v}` : "";
    }
    if (kind === "apis") {
      if (API_TOP_FIELDS.includes(field as any)) return `apis[${idx}].${field}`;
      const s = sub.trim();
      return s ? `apis[${idx}].${field}.${s}` : "";
    }
    if (kind === "steps") {
      const s = sub.trim();
      return s ? `steps[${idx}].inputs.${s}` : "";
    }
    // pre_api（含变量组：开放后测试执行页展示全部变量组供修改/新增）
    if (field === PRE_API_GROUPS_FIELD) return "pre_api_groups";
    if (PRE_API_TOP_FIELDS.includes(field as any)) return `pre_api.${field}`;
    const s = sub.trim();
    return s ? `pre_api.${field}.${s}` : "";
  };

  const path = buildPath();
  const subLabel =
    kind === "vars" ? "变量名"
    : kind === "apis" && API_TOP_FIELDS.includes(field as any) ? ""
    : kind === "pre_api" && (PRE_API_TOP_FIELDS.includes(field as any) || field === PRE_API_GROUPS_FIELD) ? ""
    : "子字段名";

  return (
    <>
      <div className="w-24">
        <label className="block text-[11px] text-[var(--color-muted)] mb-1">类型</label>
        <Select value={kind} onChange={(e) => { setKind(e.target.value as any); setIdx(0); setField("url"); setSub(""); }}>
          <option value="apis">API 字段</option>
          <option value="steps">步骤入参</option>
          <option value="vars">全局变量</option>
          <option value="pre_api">前置 API</option>
        </Select>
      </div>
      {(kind === "apis" || kind === "steps") && (
        <div className="w-32">
          <label className="block text-[11px] text-[var(--color-muted)] mb-1">{kind === "apis" ? "API" : "步骤"}</label>
          <Select value={idx} onChange={(e) => { setIdx(Number(e.target.value)); setSub(""); }}>
            {(kind === "apis" ? apis : steps).map((it, i) => (
              <option key={i} value={i}>
                {kind === "apis" ? `API ${i + 1} · ${(it as any).id}` : `步骤 ${i + 1} · ${(it as any).api_id}`}
              </option>
            ))}
          </Select>
        </div>
      )}
      {kind === "apis" && (
        <div className="w-32">
          <label className="block text-[11px] text-[var(--color-muted)] mb-1">字段</label>
          <Select value={field} onChange={(e) => { setField(e.target.value); setSub(""); }}>
            {API_TOP_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
            {API_SUB_FIELDS.map((f) => <option key={f} value={f}>{f}.*</option>)}
          </Select>
        </div>
      )}
      {kind === "pre_api" && (
        <div className="w-32">
          <label className="block text-[11px] text-[var(--color-muted)] mb-1">字段</label>
          <Select value={field} onChange={(e) => { setField(e.target.value); setSub(""); }}>
            {PRE_API_TOP_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
            {PRE_API_SUB_FIELDS.map((f) => <option key={f} value={f}>{f}.*</option>)}
            <option value={PRE_API_GROUPS_FIELD}>变量组</option>
          </Select>
        </div>
      )}
      {subLabel && (
        <div className="w-40">
          <label className="block text-[11px] text-[var(--color-muted)] mb-1">{subLabel}</label>
          {kind === "vars" && varNames.length > 0 ? (
            <Select value={sub} onChange={(e) => setSub(e.target.value)}>
              <option value="">选择…</option>
              {varNames.map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          ) : (
            <Input
              list={kind === "apis" ? "api-subkeys" : kind === "pre_api" ? "pre-api-subkeys" : "step-subkeys"}
              value={sub}
              onChange={(e) => setSub(e.target.value)}
              placeholder={subKeys.length ? "选择或输入" : "输入字段名"}
            />
          )}
          {subKeys.length > 0 && (
            <datalist id={kind === "apis" ? "api-subkeys" : kind === "pre_api" ? "pre-api-subkeys" : "step-subkeys"}>
              {subKeys.map((k) => <option key={k} value={k} />)}
            </datalist>
          )}
        </div>
      )}
      <Button
        variant="outline"
        className="h-10"
        disabled={!path}
        onClick={() => { if (path) { onAdd(path); setSub(""); } }}
      >
        <Plus size={16} /> 添加
      </Button>
    </>
  );
}

function TemplateDialog({
  open,
  templateId,
  baseTemplate,
  onClose,
}: {
  open: boolean;
  templateId: string | null;
  baseTemplate?: FlowTemplateOut;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { data: existing, isLoading } = useQuery({
    queryKey: ["flowTemplates", "get", templateId],
    queryFn: () => flowTemplates.get(templateId!),
    enabled: !!templateId,
  });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [targetConcurrency, setTargetConcurrency] = useState(3);
  const [model, setModel] = useState<ChainModel>({ name: "", variables: {}, apis: [], steps: [], fail_fast: true, final_extract: undefined });
  const [perms, setPerms] = useState<ParamPerm[]>([]);

  // 编辑态：等 existing 加载完成后再填充（useQuery 异步，不能在渲染期读）
  useEffect(() => {
    if (!open || !templateId) return;
    if (!existing) return;
    setName(existing.name || "");
    setDescription(existing.description || "");
    setTargetConcurrency(existing.target_concurrency ?? 3);
    setModel(toModel(existing.chain_json));
    setPerms(existing.param_perms || []);
  }, [open, templateId, existing]);

  // 复制态：基于已有模板预填（名称加「副本」后缀），作为新建而非更新
  useEffect(() => {
    if (!open || templateId || !baseTemplate) return;
    setName(`${baseTemplate.name}（副本）`);
    setDescription(baseTemplate.description || "");
    setTargetConcurrency(baseTemplate.target_concurrency ?? 3);
    setModel(toModel(baseTemplate.chain_json));
    setPerms(baseTemplate.param_perms || []);
  }, [open, templateId, baseTemplate]);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        description: description || null,
        chain_json: toChainJson(model),
        target_concurrency: targetConcurrency,
        param_perms: perms,
      };
      return existing ? flowTemplates.update(existing.id, body) : flowTemplates.create(body);
    },
    onSuccess: () => {
      toast("success", "已保存");
      qc.invalidateQueries({ queryKey: ["flowTemplates"] });
      onClose();
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "保存失败"),
  });

  return (
    <Dialog
      open={open}
      title={existing ? "编辑模板" : baseTemplate ? "基于模板新建" : "新建模板"}
      onClose={onClose}
      widthClass="max-w-4xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={() => save.mutate()} disabled={!name || save.isPending}>保存</Button>
        </>
      }
    >
      {templateId && isLoading ? (
        <EmptyState title="加载中…" />
      ) : (
        <div className="space-y-4">
          <Field label="模板名称" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="描述">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="被测 Agent 并发上限">
            <Input
              type="number"
              min={1}
              value={targetConcurrency}
              onChange={(e) => setTargetConcurrency(Math.max(1, parseInt(e.target.value) || 1))}
            />
          </Field>
          <div>
            <div className="mb-2 text-[11px] font-medium text-[var(--color-title)]">测试流程编排</div>
            <ChainEditor model={model} onChange={setModel} />
          </div>

          {/* 用户可编辑参数：勾选开放给普通用户 + 设置默认值（= 该字段在模板中的当前取值） */}
          <div>
            <div className="mb-2 text-[11px] font-medium text-[var(--color-title)]">用户可编辑参数</div>
            <p className="mb-3 text-[11px] text-[var(--color-muted)]">
              勾选「开放」后，普通用户在评估体系选择该模板时可自行修改此字段；「默认值」即字段在模板中的当前取值，会作为预填值展示给用户（可留空）。
            </p>
            <div className="space-y-2">
              {perms.map((p, idx) => {
                const isGroupPath = p.paramPath === "pre_api_groups" || p.paramPath.startsWith("pre_api_groups");
                const raw = getParamValue(model, p.paramPath);
                const display = raw === undefined || raw === null ? "" : typeof raw === "object" ? JSON.stringify(raw) : String(raw);
                return (
                  <div key={p.paramPath} className="flex items-center gap-3 border border-[var(--color-border)] rounded-[var(--radius-form)] px-3 py-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] text-[var(--color-title)] truncate">{paramPathLabel(p.paramPath)}</div>
                      <div className="text-[8px] text-[var(--color-muted)] font-mono truncate">{p.paramPath}</div>
                    </div>
                    <label className="flex items-center gap-1.5 text-[11px] text-[var(--color-body)] cursor-pointer shrink-0">
                      <input
                        type="checkbox"
                        checked={p.userEditable}
                        onChange={(e) =>
                          setPerms((ps) => ps.map((x, i) => (i === idx ? { ...x, userEditable: e.target.checked } : x)))
                        }
                        className="accent-[var(--brand)]"
                      />
                      开放
                    </label>
                    <div className="w-48 shrink-0">
                      <Input
                        value={display}
                        disabled={!p.userEditable}
                        placeholder={p.userEditable ? (isGroupPath ? "默认值（JSON 对象）" : "默认值（可留空）") : "未开放"}
                        onChange={(e) =>
                          setModel((m) => (isGroupPath ? patchGroupValue(m, p.paramPath, e.target.value) : patchParamValue(m, p.paramPath, e.target.value)))
                        }
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => setPerms((ps) => ps.filter((_, i) => i !== idx))}
                      title="移除该参数"
                      className="shrink-0 text-[var(--color-muted)] hover:text-[var(--color-error)] cursor-pointer"
                    >
                      <X size={15} />
                    </button>
                  </div>
                );
              })}
              {perms.length === 0 && (
                <div className="rounded-[var(--radius-form)] border border-dashed border-[var(--input-border)] p-4 text-center text-[11px] text-[var(--color-muted)]">
                  还没有开放任何参数。请在下方选择字段并点击「添加」，保存后普通用户在评估体系里就能改这些字段。
                </div>
              )}
            </div>

            {/* 添加可开放参数：按字段类型 + 定位 + 子字段 构造 paramPath */}
            <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-[var(--color-border)] pt-3">
              <AddParamPerm
                model={model}
                onAdd={(paramPath) => setPerms((ps) => (ps.some((x) => x.paramPath === paramPath) ? ps : [...ps, { paramPath, userEditable: true }]))}
              />
            </div>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function UserManager() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
  const { data: userPage, isLoading } = useQuery({
    queryKey: ["users", "list", page, pageSize],
    queryFn: () => users.list({ page, page_size: pageSize }),
  });
  const list = userPage?.items;
  const total = userPage?.total ?? 0;
  const [showCreate, setShowCreate] = useState(false);
  const [pwUser, setPwUser] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<{ id: string; name: string } | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["users"] });

  const deactivate = useMutation({
    mutationFn: (id: string) => users.deactivate(id),
    onSuccess: () => { toast("success", "已停用"); invalidate(); },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "操作失败"),
  });

  if (isLoading) return <EmptyState title="加载中…" />;

  return (
    <Card title="用户管理" extra={<Button onClick={() => setShowCreate(true)}><Plus size={16} /> 注册用户</Button>}>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
            <th className="py-2.5 px-3 font-medium">用户名</th>
            <th className="py-2.5 px-3 font-medium">显示名</th>
            <th className="py-2.5 px-3 font-medium">角色</th>
            <th className="py-2.5 px-3 font-medium">状态</th>
            <th className="py-2.5 px-3 font-medium text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          {(list || []).map((u) => (
            <tr key={u.id} className="border-b border-[var(--color-border)] last:border-0">
              <td className="py-3 px-3 text-[var(--color-title)]">{u.username}</td>
              <td className="py-3 px-3">{u.display_name || "-"}</td>
              <td className="py-3 px-3">{u.role === "admin" ? "管理员" : "普通用户"}</td>
              <td className="py-3 px-3">{u.is_active ? "正常" : "已停用"}</td>
              <td className="py-3 px-3">
                <div className="flex items-center justify-end gap-1.5">
                  <Button variant="ghost" className="h-8 px-2" onClick={() => setPwUser(u.id)}>改密</Button>
                  <Button variant="ghost" className="h-8 px-2 text-[var(--color-error)]" onClick={() => setConfirmDel({ id: u.id, name: u.username })}>
                    停用
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pagination
        page={page}
        size={pageSize}
        total={total}
        onChange={setPage}
        sizeOptions={PAGE_SIZE_OPTIONS}
        onSizeChange={setPageSize}
      />

      <CreateUserDialog open={showCreate} onClose={() => setShowCreate(false)} />
      <ChangePwDialog userId={pwUser} onClose={() => setPwUser(null)} />
      <ConfirmDialog
        open={!!confirmDel}
        title="确认停用"
        message={`确认停用用户「${confirmDel?.name}」？`}
        confirmText="停用"
        onConfirm={() => {
          if (confirmDel) deactivate.mutate(confirmDel.id);
          setConfirmDel(null);
        }}
        onCancel={() => setConfirmDel(null)}
      />
    </Card>
  );
}

function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [display, setDisplay] = useState("");
  const [ready, setReady] = useState(false);
  if (open && !ready) { setUsername(""); setPassword(""); setDisplay(""); setReady(true); }
  if (!open && ready) setReady(false);

  const save = useMutation({
    mutationFn: () => users.create(username, password, display || null),
    onSuccess: () => { toast("success", "已创建"); qc.invalidateQueries({ queryKey: ["users"] }); onClose(); },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "创建失败"),
  });

  return (
    <Dialog
      open={open}
      title="注册用户"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={() => save.mutate()} disabled={!username || !password || save.isPending}>创建</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="用户名" required><Input value={username} onChange={(e) => setUsername(e.target.value)} /></Field>
        <Field label="密码" required><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <Field label="显示名"><Input value={display} onChange={(e) => setDisplay(e.target.value)} /></Field>
      </div>
    </Dialog>
  );
}

function ChangePwDialog({ userId, onClose }: { userId: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const open = !!userId;
  const [password, setPassword] = useState("");
  const [ready, setReady] = useState(false);
  if (open && !ready) { setPassword(""); setReady(true); }
  if (!open && ready) setReady(false);

  const save = useMutation({
    mutationFn: () => users.changePassword(userId!, password),
    onSuccess: () => { toast("success", "已修改"); qc.invalidateQueries({ queryKey: ["users"] }); onClose(); },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "修改失败"),
  });

  return (
    <Dialog
      open={open}
      title="修改密码"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={() => save.mutate()} disabled={!password || save.isPending}>保存</Button>
        </>
      }
    >
      <Field label="新密码" required>
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
    </Dialog>
  );
}

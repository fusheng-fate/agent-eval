// 33 接口封装，按后端模块分组导出。每个函数对应 docs/服务化数据模型与接口.md 的一个接口。
import { api, apiUnwrapped, apiUpload, apiDownload, type Query } from "./http";
import type {
  UserOut, TokenResp, Msg, RunOut, CaseResultOut, MetricOut, StandardEvaluatorOut,
  DatasetOut, DatasetPreviewOut, CaseOut, FlowTemplateOut, ReportOut, ConfigOut,
  DashboardSummary, ColumnMapping, EvalImportColumnMapping, RunCreateReq, SelfCheckExecResp, RunLogOut,
} from "./types";

// ---------- auth ----------
// 注意：auth 模块接口返回 {code,message,data} 包裹，需用 apiUnwrapped 解包出 data。
// 其余 33 个接口仍是裸返回，继续用 api。
export const auth = {
  login: (username: string, password: string) =>
    apiUnwrapped<TokenResp>("/auth/login", { method: "POST", body: { username, password } }),
  me: () => apiUnwrapped<UserOut>("/auth/me"),
  changeOwnPassword: (password: string) =>
    apiUnwrapped<Msg>("/auth/me/password", { method: "POST", body: { password } }),
  refresh: (refresh_token: string) =>
    apiUnwrapped<Omit<TokenResp, "user">>("/auth/refresh", { method: "POST", body: { refresh_token } }),
  logout: () => apiUnwrapped<Msg>("/auth/logout", { method: "POST" }),
};

// 后端统一分页结构（部分列表接口返回此结构而非裸数组）。
export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
// 分页查询参数：page_size 缺省按 100 取（前端列表页需要全量），显式传值则尊重调用方。
type PageQuery = { page?: number; page_size?: number } & Record<string, unknown>;
const paged = (q?: PageQuery) => ({ page: 1, page_size: 100, ...q });

// ---------- users（admin） ----------
export const users = {
  list: (q?: { page?: number; page_size?: number }) => api<Page<UserOut>>("/users", { params: q }),
  create: (username: string, password: string, display_name: string | null) =>
    api<UserOut>("/users", { method: "POST", body: { username, password, display_name } }),
  changePassword: (userId: string, password: string) =>
    api<Msg>(`/users/${userId}/password`, { method: "POST", body: { password } }),
  deactivate: (userId: string) => api<Msg>(`/users/${userId}/deactivate`, { method: "POST" }),
};

// ---------- metrics ----------
// 后端 /metrics 返回分页结构（含 total）；调用方按需取 .items 或传 page/page_size 做服务端分页。
export const metrics = {
  list: (q?: PageQuery) => api<Page<MetricOut>>("/metrics", { params: paged(q) }),
  get: (id: string) => api<MetricOut>(`/metrics/${id}`),
  create: (b: { name: string; category?: string; industry?: string | null; description?: string | null; skill_md: string }) =>
    api<MetricOut>("/metrics", { method: "POST", body: b }),
  update: (id: string, b: Partial<{ name: string; category: string; industry: string | null; description: string | null; skill_md: string }>) =>
    api<MetricOut>(`/metrics/${id}/update`, { method: "POST", body: b }),
  remove: (id: string) => api<Msg>(`/metrics/${id}/delete`, { method: "POST" }),
  options: () => api<Array<{ id: string; name: string }>>("/metrics/options"),
};

// ---------- evaluators ----------
export const evaluators = {
  getStandard: () => api<StandardEvaluatorOut>("/evaluators/standard"),
  updateStandard: (b: { description: string | null; metrics: Array<{ metric_id: string; weight: number }> }) =>
    api<StandardEvaluatorOut>("/evaluators/standard/update", { method: "POST", body: b }),
};

// ---------- datasets ----------
// 后端 /datasets 返回分页结构；前端需要全量，取 items 数组返回（调用方按数组用）。
export const datasets = {
  // 返回完整分页结构；调用方可取 .items（全量，默认 page_size=100）或传 page/page_size 做分页。
  list: (q?: PageQuery) => api<Page<DatasetOut>>("/datasets", { params: paged(q) }),
  get: (id: string) => api<DatasetOut>(`/datasets/${id}`),
  preview: (id: string) => api<DatasetPreviewOut>(`/datasets/${id}/preview`),
  cases: (id: string, q?: PageQuery) =>
    api<Page<CaseOut>>(`/datasets/${id}/cases`, { params: paged(q) }),
  casesBatch: (id: string, caseNos: string[]) =>
    api<CaseOut[]>(`/datasets/${id}/cases/batch`, { method: "POST", body: { case_nos: caseNos } }),
  upload: (file: File, name: string, columnMapping: ColumnMapping) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    form.append("column_mapping", JSON.stringify(columnMapping));
    return apiUpload<DatasetOut>("/datasets/upload", form);
  },
  rename: (id: string, name: string) =>
    api<DatasetOut>(`/datasets/${id}/rename`, { method: "POST", body: { name } }),
  download: (id: string) => apiDownload(`/datasets/${id}/download`, `dataset_${id}.xlsx`),
  remove: (id: string) => api<Msg>(`/datasets/${id}/delete`, { method: "POST" }),
  batchDelete: (ids: string[]) => api<{ deleted: number }>(`/datasets/batch-delete`, { method: "POST", body: { ids } }),
  uploaders: () => api<string[]>("/datasets/uploaders"),
};

// ---------- flowTemplates ----------
export const flowTemplates = {
  list: () => api<FlowTemplateOut[]>("/flow-templates"),
  listPaged: (q: { keyword?: string; page: number; page_size: number }) =>
    api<Page<FlowTemplateOut>>("/flow-templates", { params: { keyword: q.keyword, page: q.page, page_size: q.page_size } }),
  get: (id: string) => api<FlowTemplateOut>(`/flow-templates/${id}`),
  create: (b: { name: string; description: string | null; chain_json: unknown; param_perms: Array<{ paramPath: string; userEditable: boolean }> }) =>
    api<FlowTemplateOut>("/flow-templates", { method: "POST", body: b }),
  update: (id: string, b: { name: string; description: string | null; chain_json: unknown; param_perms: Array<{ paramPath: string; userEditable: boolean }> }) =>
    api<FlowTemplateOut>(`/flow-templates/${id}/update`, { method: "POST", body: b }),
  remove: (id: string) => api<Msg>(`/flow-templates/${id}/delete`, { method: "POST" }),
  validate: (id: string) => api<Msg>(`/flow-templates/${id}/validate`, { method: "POST" }),
};

// ---------- runs ----------
export const runs = {
  create: (b: RunCreateReq) => api<RunOut>("/runs", { method: "POST", body: b }),
  // 导入评测结果 Excel → 建任务异步打分（mode=eval_import，跳过调被测 Agent）
  import: (file: File, task_name: string, columnMapping: EvalImportColumnMapping, extra_metric_ids: string[] = []) => {
    const form = new FormData();
    form.append("file", file);
    form.append("task_name", task_name);
    form.append("column_mapping", JSON.stringify(columnMapping));
    form.append("extra_metric_ids", JSON.stringify(extra_metric_ids));
    return apiUpload<RunOut>("/runs/import", form);
  },
  // 后端 /runs 返回分页结构；前端需要全量，取 items 数组返回（调用方按数组用）。
  list: (q?: Query) => api<Page<RunOut>>("/runs", { params: paged(q) }),
  get: (id: string) => api<RunOut>(`/runs/${id}`),
  cases: async (id: string, q?: { page?: number; page_size?: number }) =>
    (await api<Page<CaseResultOut>>(`/runs/${id}/cases`, { params: paged(q) })).items,
  // 返回完整分页结构（含 total），供列表页做前端分页。
  casesPaged: (id: string, q?: { page?: number; page_size?: number }) =>
    api<Page<CaseResultOut>>(`/runs/${id}/cases`, { params: paged(q) }),
  case: (id: string, caseResultId: string) => api<CaseResultOut>(`/runs/${id}/cases/${caseResultId}`),
  pause: (id: string) => api<RunOut>(`/runs/${id}/pause`, { method: "POST" }),
  resume: (id: string) => api<RunOut>(`/runs/${id}/resume`, { method: "POST" }),
  stop: (id: string) => api<RunOut>(`/runs/${id}/stop`, { method: "POST" }),
  remove: (id: string) => api<Msg>(`/runs/${id}/delete`, { method: "POST" }),
  export: (id: string, level: "exec" | "eval" = "eval") =>
    apiDownload(`/runs/${id}/export?level=${level}`, `run_${id}.xlsx`),
  // 执行自检：失败也返回 HTTP 200（data.ok=false），调用方需判 data.ok 而非依赖抛错
  selfcheckExec: (b: RunCreateReq) => api<SelfCheckExecResp>("/runs/selfcheck/exec", { method: "POST", body: b }),
  selfcheckEval: () => api<Msg>("/runs/selfcheck/eval", { method: "POST" }),
  logs: (id: string) => api<RunLogOut[]>(`/runs/${id}/logs`),
};

// ---------- reports ----------
export const reports = {
  // 后端 /reports 返回分页结构（含 total）；调用方按需取 .items 或传 page/page_size 做服务端分页。
  list: (q?: PageQuery) => api<Page<ReportOut>>("/reports", { params: paged(q) }),
  get: (id: string) => api<ReportOut>(`/reports/${id}`),
  exportHtml: (id: string) => apiDownload(`/reports/${id}/export.html`, `report_${id}.html`),
  remove: (id: string) => api<Msg>(`/reports/${id}/delete`, { method: "POST" }),
};

// ---------- configs ----------
// 更新统一走批量接口 POST /configs/batch-update（v1.1 移除单 key 更新）。
// 改单个 key 就传一个键；value 可为任意 JSON。响应 {updated, skipped}。
export interface ConfigUpdateResult {
  updated: string[];
  skipped: string[];
}
export const configs = {
  list: () => api<ConfigOut[]>("/configs"),
  get: (key: string) => api<ConfigOut>(`/configs/${key}`),
  update: (key: string, config_value: unknown) =>
    api<ConfigUpdateResult>("/configs/batch-update", { method: "POST", body: { values: { [key]: config_value } } }),
  batchUpdate: (values: Record<string, unknown>) =>
    api<ConfigUpdateResult>("/configs/batch-update", { method: "POST", body: { values } }),
  /** 手动刷新动态 token（强制绕过缓存，验证取 token 链路）。
   *  auth 为前端表单草稿（AuthConfig），传入时以草稿为准测试，让用户保存前即可验证。 */
  refreshLlmToken: (auth?: Record<string, unknown>) =>
    api<{ message: string; token_preview: string; cache_ttl: number }>("/runs/selfcheck/llm-token", { method: "POST", body: auth ?? {} }),
};

// ---------- dashboard ----------
export const dashboard = {
  summary: (q?: Query) => api<DashboardSummary>("/dashboard/summary", { params: q }),
};

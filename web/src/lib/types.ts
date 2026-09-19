// 后端 schema 的 TS 类型。
// 命名约定：顶层响应多为 snake_case；JSON 列里是 camelCase（见各注释）。

export type Role = "admin" | "tester";

export interface UserOut {
  id: string;
  username: string;
  display_name: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface TokenResp {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: UserOut;
}

export interface Msg {
  message: string;
  ok: boolean;
}

export type RunStatus = "pending" | "running" | "paused" | "done" | "stopped" | "error";

export interface RunOut {
  id: string;
  task_name: string;
  owner_id: string;
  /** 发起人用户名（列表接口由后端 join users 带出，详情可能为 null）。 */
  username: string | null;
  /** 关联数据集 id（任务创建时所选数据集）。 */
  dataset_id: string;
  /** 关联流程模板 id（任务创建时所选测试环境/流程模板）。 */
  flow_template_id: string;
  /** 任务类型：exec=执行任务 / eval_import=评测结果打分任务。 */
  mode?: "exec" | "eval_import";
  status: RunStatus;
  total_cases: number;
  done_cases: number;
  passed_cases: number;
  failed_cases: number;
  overall_score: number | null;
  model_concurrency: number;
  target_concurrency: number;
  /** 轮次大小（每组用例数），exec 模式有值。 */
  round_size?: number | null;
  /** 总轮次数。 */
  total_rounds?: number | null;
  /** 已完成轮次数。 */
  done_rounds?: number | null;
  /** 用例执行耗时（秒）= Σ 调被测 Agent 耗时。 */
  exec_sec: number | null;
  /** 结果打分耗时（秒）= Σ 调 LLM 打分耗时。 */
  score_sec: number | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  /** 打分状态：scored=已打分 / pending=待打分（后端按 status 派生）。 */
  score_status: "scored" | "pending";
  /** 关联报告 ID（任务完成后生成，无则为 null）。 */
  report_id: string | null;
}

// 标准/额外指标项（JSON 列，camelCase）。
// 注意：后端已移除逐指标的 threshold/passed——达标判定在评估器级（overallScore >= pass_threshold）。
export interface StandardMetricItem {
  metricId: string;
  name: string;
  weight: number;
  score: number;
  reason: string;
}

export interface ExtraMetricItem {
  metricId: string;
  name: string;
  score: number;
  reason: string;
}

export type CaseStatus = "pending" | "running" | "executed" | "scoring" | "passed" | "failed" | "error" | "skipped";

// 失败归因（仅 failed 用例有值，passed 为 null；旧数据为 null，需容错）。
// primary 分类：事实错误 / 逻辑缺陷 / 格式不符 / 信息缺失 / 其他。
export interface FailureAttributionItem {
  type: string;
  label: string;
  reason: string;
  evidence: string;
}

export interface FailureAttribution {
  primary: string;
  items: FailureAttributionItem[];
  reason: string;
}

export interface CaseResultOut {
  id: string;
  case_id: string;
  case_no: string | null;
  status: CaseStatus;
  overall_score: number | null;
  standard_metrics: StandardMetricItem[] | null;
  extra_metrics: ExtraMetricItem[] | null;
  brief_comment: string | null;
  /** 失败归因，仅 failed 用例有值。 */
  failure_attribution: FailureAttribution | null;
  agent_output: string | null;
  token_usage: number | null;
  latency_sec: number | null;
  error_msg: string | null;
  /** 被测 Agent 逐步请求/响应轨迹（定位问题用） */
  target_trace: SelfCheckTraceStep[] | null;
}

export interface MetricOut {
  id: string;
  name: string;
  category: string; // tech | biz
  industry: string | null;
  description: string | null;
  skill_md: string;
  is_builtin: boolean;
  created_at: string;
}

// 标准评估器（metrics[] 为 camelCase）
export interface StandardEvaluatorOut {
  id: string;
  name: string;
  description: string | null;
  metrics: Array<{
    metricId: string;
    name: string;
    category: string;
    industry: string;
    description: string;
    weight: number;
  }>;
}

export interface DatasetOut {
  id: string;
  name: string;
  case_count: number;
  source: string;
  owner_id: string;
  /** 上传人（归属人）用户名，v1.1 新增，由后端 join users 带出。 */
  username: string | null;
  created_at: string;
}

export interface DatasetPreviewOut {
  dataset_id: string;
  name: string;
  case_count: number;
  headers: string[];
  rows: unknown[][];
}

export interface CaseOut {
  id: string;
  case_no: string;
  user_input: string;
  expected_gt: string;
  dimension_l1: string | null;
  dimension_l2: string | null;
  preset: string | null;
  steps: string | null;
  tags: string[] | null;
  extra: Record<string, unknown> | null;
}

// 流程模板（param_perms 为 camelCase；chain_json 自由结构）
export interface ChainApi {
  id: string;
  method: string;
  url: string;
  headers?: Record<string, string>;
  query?: Record<string, string>;
  body?: unknown;
  timeout?: number;
  retry?: number;
  extract?: Record<string, string>;
  extract_to_result?: Record<string, string>;
}

export interface ChainStep {
  api_id: string;
  inputs: Record<string, unknown>;
}

// final_extract 两种形态（v1.3）：
//   - string：JSONPath，从最后一步响应提取单字段（兼容旧）
//   - Record：跨步骤多字段，{字段名: {step?: 步骤序号(0-based,缺省最后一步), path: JSONPath}}
export type FinalExtract = string | Record<string, { step?: number; path: string }>;

// 前置 API（v1.5+，需 enabled=true 且 url 非空才执行）
export interface ChainPreApi {
  enabled?: boolean;
  method?: string;
  url?: string;
  headers?: Record<string, string>;
  query?: Record<string, string>;
  body?: unknown;
  body_type?: "json" | "form";
  timeout?: number;
  retry?: number;
  extract?: Record<string, string>;
  ttl_seconds?: number;
}

export interface ChainJson {
  apis: ChainApi[];
  steps: ChainStep[];
  variables?: Record<string, unknown>;
  final_extract?: FinalExtract;
  pre_api?: ChainPreApi;
  pre_api_groups?: Record<string, string>[];
}

// 模板参数开放配置（P13）：paramPath 指向 chain_json 中某字段，userEditable 决定是否开放给普通用户。
// defaultValue 为前端概念——该字段在模板中的当前取值即「默认值」（后端仅存 param_path + user_editable，无独立默认值列）。
export interface ParamPerm {
  paramPath: string;
  userEditable: boolean;
  defaultValue?: string;
}

export interface FlowTemplateOut {
  id: string;
  name: string;
  description: string | null;
  chain_json: ChainJson;
  target_concurrency: number;
  param_perms: ParamPerm[];
  created_at: string;
}

// 报告（子结构 camelCase，见 report_service.py）
export interface ReportOut {
  id: string;
  run_id: string;
  task_name: string;
  owner_id: string;
  /** 创建人用户名，列表接口由后端 join users 带出（详情接口可能为 null）。 */
  username: string | null;
  summary: {
    overallScore: number;
    total: number;
    passed: number;
    failed: number;
    tokenUsage: number;
    avgLatencySec: number;
    /** 用例执行耗时（秒），后端新增；旧报告数据可能为 undefined。 */
    execSec?: number | null;
    /** 结果打分耗时（秒），后端新增；旧报告数据可能为 undefined。 */
    scoreSec?: number | null;
  };
  standard_metric_averages: Array<{ metricId: string; name: string; weight: number; avgScore: number }> | null;
  extra_metric_averages: Array<{ metricId: string; name: string; avgScore: number }> | null;
  dimension_summary: Array<{ l1: string; l2: string; total: number; passed: number; failed: number; avgScore: number; cases?: Array<{ caseNo: string; status: string; overallScore: number | null }> }> | null;
  case_details: Array<{
    caseId: string;
    caseNo: string;
    status: string;
    overallScore: number | null;
    standardMetrics: StandardMetricItem[] | null;
    extraMetrics: ExtraMetricItem[] | null;
    briefComment: string | null;
    agentOutput: string | null;
    latencySec: number | null;
    tokenUsage: number | null;
    errorMsg: string | null;
    /** 失败归因，仅 failed 用例有值。 */
    failureAttribution: FailureAttribution | null;
  }> | null;
  /** 失败归因分布：failed 用例 primary 分类计数。 */
  failure_root_causes: Array<{ category: string; count: number; cases?: Array<{ caseNo: string; status: string; overallScore: number | null }> }> | null;
  created_at: string;
}

export interface ConfigOut {
  config_key: string;
  config_value: unknown;
  scope: string; // global | personal
  editable_by: string; // admin | user
  description: string | null;
}

export interface DashboardSummary {
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  pass_rate: number;
  total_runs: number;
  running_runs: number;
  token_usage: number;
  avg_latency_sec: number;
}

// 数据集列映射（上传时序列化为 JSON 字符串）
export interface ColumnMapping {
  case_no: string;
  user_input: string;
  expected_gt: string;
  dimension_l1?: string | null;
  dimension_l2?: string | null;
}

// 评测结果打分导入的列映射（比数据集多 agent_output 必填列）
export interface EvalImportColumnMapping {
  case_no: string;
  user_input: string;
  expected_gt: string;
  agent_output: string;
  dimension_l1?: string | null;
  dimension_l2?: string | null;
}

// 创建任务
export interface RunCreateReq {
  task_name: string;
  dataset_id: string;
  flow_template_id: string;
  extra_metric_ids?: string[];
  overrides?: Record<string, unknown>;
  round_size?: number;
}

// 执行自检：逐步请求/响应轨迹（定位被测 Agent 链路错误用）
export interface SelfCheckTraceStep {
  api_id: string;
  method: string;
  url: string;
  headers: Record<string, unknown> | null;
  query: Record<string, unknown> | null;
  body: Record<string, unknown> | null;
  status: number | null;
  error: string | null;
  response: unknown;
}

export interface SelfCheckExecResp {
  message: string;
  ok: boolean;
  trace: SelfCheckTraceStep[];
}

// 任务执行日志（terminal 风格展示）
export interface RunLogOut {
  id: string;
  level: "info" | "success" | "warn" | "error";
  message: string;
  created_at: string;
}

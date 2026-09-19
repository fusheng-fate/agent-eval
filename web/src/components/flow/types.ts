// ============================================================
// API 调用链路编排 — 前端类型定义
// 移植自 reference/legacy/page-src/.../apiChain/types.ts（仅编排编辑所需部分）
// ============================================================

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD" | "OPTIONS";
export type AuthType = "none" | "static" | "dynamic";
export type OnError = "abort" | "continue" | "retry";
export type TokenIn = "header" | "query";

export interface TokenApiConfig {
  method: HttpMethod;
  url: string;
  headers: Record<string, string>;
  query: Record<string, string>;
  body: unknown;
  extract: string;
  ttl: number;
  timeout: number;
}

export interface AuthConfig {
  type: AuthType;
  static_token?: string;
  token_in: TokenIn;
  token_name: string;
  token_prefix: string;
  token_api?: TokenApiConfig;
}

export interface ApiSchema {
  id: string;
  name?: string;
  method: HttpMethod;
  url: string;
  headers?: Record<string, string>;
  query?: Record<string, string>;
  body?: unknown;
  body_type?: "json" | "form";
  auth?: AuthConfig;
  timeout: number;
  extract?: Record<string, string>;
  extract_to_result?: Record<string, string>;
  on_error: OnError;
  retry: number;
  retry_delay?: number;
}

export interface Step {
  id: string;
  api_id: string;
  inputs?: Record<string, string>;
  optional?: boolean;
}

/** final_extract 单个字段提取项（dict 形态，v1.3 跨步骤多字段） */
export interface FinalExtractField {
  step?: number; // 步骤序号 0-based，缺省 = 最后一步
  path: string;  // JSONPath，如 data.answer / a[0].b
}

/** final_extract：string（最后一步单字段，兼容旧）| dict（跨步骤多字段） */
export type FinalExtract = string | Record<string, FinalExtractField>;

/** 前置 API（获取 session 等，每组开始前调一次） */
export interface PreApi {
  /** 是否启用：仅 true 时才调用；缺省/false 均不执行（v1.5 前无此字段=默认执行） */
  enabled?: boolean;
  method: HttpMethod;
  url: string;
  headers?: Record<string, string>;
  query?: Record<string, string>;
  body?: unknown;
  body_type?: "json" | "form";  // 默认 json
  timeout?: number;
  retry?: number;
  extract?: Record<string, string>;  // {变量名: JSONPath}
  ttl_seconds?: number;  // session 缓存有效期（秒）
}

/** 变量组（轮次模式按轮次循环；非轮次模式按用例顺序循环，v1.6） */
export interface PreApiGroup {
  [key: string]: string;  // {phone: "13800000001", device_id: "DEV001", ...}
}

/** 链路模型（编辑器数据） */
export interface ChainModel {
  name: string;
  variables: Record<string, string>;
  apis: ApiSchema[];
  steps: Step[];
  fail_fast: boolean;
  final_extract?: FinalExtract;
  pre_api?: PreApi;
  pre_api_groups?: PreApiGroup[];
}

export const HTTP_METHODS: HttpMethod[] = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];

export function defaultAuth(): AuthConfig {
  return { type: "none", token_in: "header", token_name: "Authorization", token_prefix: "" };
}

export function defaultTokenApi(): TokenApiConfig {
  return {
    method: "POST",
    url: "",
    headers: {},
    query: {},
    body: null,
    extract: "$.access_token",
    ttl: 300,
    timeout: 15,
  };
}

export function newApi(n: number): ApiSchema {
  return {
    id: `api${n}`,
    name: "",
    method: "GET",
    url: "",
    headers: {},
    query: {},
    body: null,
    body_type: "json",
    auth: defaultAuth(),
    timeout: 30,
    extract: {},
    extract_to_result: {},
    on_error: "abort",
    retry: 0,
  };
}

export function newStep(n: number, firstApiId: string): Step {
  return { id: `s${n}`, api_id: firstApiId, inputs: {}, optional: false };
}

/** 确保 auth / token_api 结构完整（渲染前兜底） */
export function ensureAuth(a: ApiSchema): AuthConfig {
  if (!a.auth) a.auth = defaultAuth();
  if (a.auth.type === "dynamic" && !a.auth.token_api) {
    a.auth.token_api = defaultTokenApi();
  }
  if (a.auth.type === "dynamic" && a.auth.token_api) {
    if (!a.auth.token_api.headers) a.auth.token_api.headers = {};
    if (!a.auth.token_api.query) a.auth.token_api.query = {};
  }
  return a.auth;
}

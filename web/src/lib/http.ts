// 统一请求层：配置化 base + JWT 拦截器 + 统一错误处理（去 hostBridge、去裸 fetch）。
const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";
const TOKEN_KEY = "token";
const REFRESH_KEY = "refresh_token";

let token: string | null = localStorage.getItem(TOKEN_KEY);
let refreshToken: string | null = localStorage.getItem(REFRESH_KEY);

export function getToken(): string | null {
  return token;
}

/** 设置 access token（同步内存 + localStorage）。传 null 清除。 */
export function setToken(t: string | null): void {
  token = t;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

/** 设置 refresh token。传 null 清除。 */
export function setRefreshToken(t: string | null): void {
  refreshToken = t;
  if (t) localStorage.setItem(REFRESH_KEY, t);
  else localStorage.removeItem(REFRESH_KEY);
}

/** 清除全部登录态（access + refresh）。 */
export function clearAuth(): void {
  setToken(null);
  setRefreshToken(null);
}

// 用 refresh_token 换新的 access_token。成功返回 true；失败返回 false。
let refreshing: Promise<boolean> | null = null;
async function tryRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return false;
        const json = await res.json();
        const data = json?.data; // auth 接口统一 {code,message,data} 包裹
        if (!data?.access_token) return false;
        setToken(data.access_token);
        if (data.refresh_token) setRefreshToken(data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        // 延迟清空，避免同一批并发 401 重复刷新
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, msg: string) {
    super(msg);
    this.status = status;
    this.name = "ApiError";
  }
}

export type Query = Record<string, string | number | undefined | null>;

interface ApiOpts {
  method?: string;
  body?: unknown;
  params?: Query;
  signal?: AbortSignal;
}

function buildQuery(params?: ApiOpts["params"]): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

function handleUnauthorized(): void {
  clearAuth();
  const path = window.location.pathname;
  if (path !== "/login") {
    const redirect = encodeURIComponent(path);
    window.location.href = `/login?redirect=${redirect}`;
  }
}

// 401 时先尝试用 refresh_token 静默续期并重试一次；续期失败才跳登录。
async function doFetch(path: string, init: RequestInit): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (res.status === 401 && refreshToken) {
    const okRefresh = await tryRefresh();
    if (okRefresh) {
      // 用新 token 重试原请求
      const headers = new Headers(init.headers);
      headers.set("Authorization", `Bearer ${token}`);
      return fetch(`${API_BASE}${path}`, { ...init, headers });
    }
  }
  return res;
}

async function parseError(res: Response): Promise<never> {
  let msg = res.statusText || `请求失败 (${res.status})`;
  try {
    const data = await res.json();
    if (data?.detail) {
      msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    }
  } catch {
    /* 非 JSON 错误体，忽略 */
  }
  throw new ApiError(res.status, msg);
}

// 后端统一响应包裹 {code, message, data}（迁移中：部分接口已包裹，部分仍裸返回）。
// 统一在这里解包：是包裹就取 data（code!==0 抛业务错误），否则原样返回。
function unwrap<T>(json: unknown): T {
  if (json && typeof json === "object" && !Array.isArray(json) && "code" in json) {
    const env = json as { code: number; message?: string; data?: T };
    if (env.code !== 0) throw new ApiError(200, env.message || "业务错误");
    return env.data as T;
  }
  return json as T;
}

/** 核心请求：JSON 入/出，自动解 {code,message,data} 包裹。204 返回 undefined。 */
export async function api<T>(path: string, opts: ApiOpts = {}): Promise<T> {
  const { method = "GET", body, params, signal } = opts;
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await doFetch(`${path}${buildQuery(params)}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (res.status === 401) {
    handleUnauthorized();
    throw new ApiError(401, "未登录");
  }
  if (!res.ok) await parseError(res);
  if (res.status === 204) return undefined as T;
  return unwrap<T>(await res.json());
}

/** 别名：显式表示该接口走统一包裹结构（当前 api 已自动解包，二者等价）。 */
export const apiUnwrapped = api;

/** 文件上传（FormData，不设 JSON content-type）。 */
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await doFetch(path, { method: "POST", headers, body: form });
  if (res.status === 401) {
    handleUnauthorized();
    throw new ApiError(401, "未登录");
  }
  if (!res.ok) await parseError(res);
  return unwrap<T>(await res.json());
}

/** 下载（blob），触发浏览器保存。 */
export async function apiDownload(path: string, filename?: string): Promise<void> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await doFetch(path, { headers });
  if (res.status === 401) {
    handleUnauthorized();
    throw new ApiError(401, "未登录");
  }
  if (!res.ok) await parseError(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

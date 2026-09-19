"""LLM 评测调用（纯 HTTP，无子进程）。

评分 prompt = 指标 skill_md 的评分要求 + 用例上下文（测试输入/被测输出/预期结果）。
同一次调用顺带输出 brief_comment（P18）。
"""
import hashlib
import json
import logging
import time
from typing import Any

import httpx

from ...core.redis_client import get_redis

log = logging.getLogger("llm")

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 3.0  # 秒，重试间隔

# 默认认证方式（llm.auth 缺省时）：static，token 取 llm.api_key，放 Authorization: Bearer
DEFAULT_AUTH = {"type": "static", "token_in": "header", "token_name": "Authorization", "token_prefix": "Bearer "}

# 动态 token 提前量（秒）：缓存比 token 真实寿命早这么多过期，
# 使"快失效"时缓存已先过期，下一次评分自然重取，避免"缓存还在但 token 已死"的 401。
REFRESH_AHEAD_SEC = 60

# 评分结果结构化输出工具：强制裁判模型以 tool_call 返回打分 JSON，
# 避免从自由文本 content 里抠 JSON 的格式漂移问题。
SCORE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_score",
        "description": "提交所有指标的评测打分结果",
        "parameters": {
            "type": "object",
            "properties": {
                "standard_metrics": {
                    "type": "array",
                    "description": "标准指标评分列表（参与加权主分）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "metric_id": {"type": "string", "description": "指标 ID（与 prompt 中给出的 metricId 一致）"},
                            "score": {"type": "number", "description": "0-100 的评分（百分制）"},
                            "reason": {"type": "string", "description": "评分理由"},
                        },
                        "required": ["metric_id", "score", "reason"],
                    },
                },
                "extra_metrics": {
                    "type": "array",
                    "description": "额外指标评分列表（单独计分，不进主分）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "metric_id": {"type": "string", "description": "指标 ID（与 prompt 中给出的 metricId 一致）"},
                            "score": {"type": "number", "description": "0-100 的评分（百分制）"},
                            "reason": {"type": "string", "description": "评分理由"},
                        },
                        "required": ["metric_id", "score", "reason"],
                    },
                },
                "brief_comment": {"type": "string", "description": "一句话总体评分说明（通过/失败都要给，言简意赅，直接说明打分依据；开头不要用「Agent」等字样）"},
                "failure_attribution": {
                    "type": ["object", "null"],
                    "description": "失败归因（评分通过时为 null）",
                    "properties": {
                        "primary": {"type": "string", "description": "主归因分类"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "label": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "evidence": {"type": "string"},
                                },
                            },
                        },
                        "reason": {"type": "string"},
                    },
                },
            },
            "required": ["standard_metrics", "extra_metrics", "brief_comment"],
        },
    },
}


def _is_retryable(exc: Exception) -> bool:
    """网络错误/超时/5xx 可重试；4xx 不重试。"""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def build_score_prompt(
    std_metrics: list[dict],
    extra_metrics: list[dict],
    case: dict,
    agent_output: str,
) -> str:
    """拼多指标评分 prompt（一次评所有指标）。

    std_metrics: [{id, name, weight, skill_md}]
    extra_metrics: [{id, name, skill_md}]
    """
    parts = [
        "你是严格的评测裁判，请对 Agent 输出按以下所有指标逐一打分（0-100 分，百分制）。\n",
        "每个指标独立评分，互不影响。请通过 submit_score 工具一次性提交所有指标的评分结果。\n",
    ]
    if std_metrics:
        parts.append("## 标准指标（参与加权主分）\n")
        for i, m in enumerate(std_metrics, 1):
            parts.append(f"### {i}. {m['name']}（metricId: {m['id']}，权重: {m.get('weight', 1)}）\n")
            parts.append(f"评分要求：{m.get('skill_md', '')}\n\n")
    if extra_metrics:
        parts.append("## 额外指标（单独计分，不进主分）\n")
        for i, m in enumerate(extra_metrics, 1):
            parts.append(f"### {i}. {m['name']}（metricId: {m['id']}）\n")
            parts.append(f"评分要求：{m.get('skill_md', '')}\n\n")
    parts += [
        f"## 测试输入\n{case.get('user_input', '')}\n",
        f"## 预期结果\n{case.get('expected_gt', '')}\n",
        f"## Agent 实际输出\n{agent_output}\n",
        "请通过 submit_score 工具提交评分结果：",
        "- standard_metrics: 标准指标评分数组，每项含 metric_id / score(0-100) / reason",
        "- extra_metrics: 额外指标评分数组，每项含 metric_id / score(0-100) / reason",
        "- brief_comment: 一句话总体评分说明（通过/失败都要给，言简意赅，开头不要用「Agent」等字样）",
        "- failure_attribution: 失败归因（评分通过时为 null）",
    ]
    return "\n".join(parts)


def _extract_path(obj: Any, path: str) -> Any:
    """极简 JSONPath：a.b.c / a[0].b，兼容 $. 前缀（与 target_client 一致）。"""
    path = (path or "").strip()
    if path.startswith("$."):
        path = path[2:]
    cur = obj
    for part in path.replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _auth_fingerprint(auth: dict) -> str:
    """token_api 配置指纹：任一字段变化 → 缓存失效（强制重新取 token）。"""
    ta = auth.get("token_api") or {}
    raw = json.dumps(ta, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def invalidate_llm_token_cache(auth: dict) -> None:
    """清掉动态 token 缓存（401 自愈时调用，强制下次重取）。"""
    try:
        get_redis().delete(f"agent_eval:llm_token:{_auth_fingerprint(auth)}")
    except Exception:  # noqa: BLE001  清缓存失败不影响主流程
        log.warning("清 LLM token 缓存失败", exc_info=True)


def resolve_llm_token(db, config: dict) -> tuple[str, dict[str, str]]:
    """按 llm.auth 解析出本次调用的 token 与 query 参数。

    返回 (token, query_params)：
    - none   → ("", {})
    - static → (config["api_key"], {})
    - dynamic → 查 Redis 全局缓存（key 含 token_api 指纹，TTL=token_api.ttl）；
      未命中则调 token 接口 → JSONPath extract 解析 token → 写回 llm.api_key（commit）+ 写 Redis。

    query_params 非空时，token 放 query（token_in=query）；否则放 header（token_in=header）。
    动态取 token 失败抛异常（由调用方按 LLM 调用失败处理）。
    """
    auth = config.get("auth") or DEFAULT_AUTH
    atype = auth.get("type", "static")
    if atype == "none":
        return "", {}
    if atype == "static":
        # 静态：固定 Bearer + api_key（前端静态态不暴露 prefix，统一 Bearer 语义）
        return (f"Bearer {config.get('api_key')}".strip()), {}

    # dynamic
    ta = auth.get("token_api") or {}
    url = str(ta.get("url") or "").strip()
    if not url:
        raise RuntimeError("动态 token 未配置接口 url")
    ttl = int(ta.get("ttl") or 300)
    timeout = float(ta.get("timeout") or 15)
    # 提前量：缓存比 token 真实寿命早 REFRESH_AHEAD_SEC 过期，快失效时先过期→下次重取
    cache_ttl = max(1, ttl - REFRESH_AHEAD_SEC)
    cache_key = f"agent_eval:llm_token:{_auth_fingerprint(auth)}"
    r = get_redis()
    cached = r.get(cache_key)
    if cached:
        token = cached if isinstance(cached, str) else cached.decode("utf-8")
        return token, {}

    method = str(ta.get("method") or "POST").upper()
    headers = dict(ta.get("headers") or {})
    query = dict(ta.get("query") or {})
    body = ta.get("body")
    body_type = "form" if isinstance(body, dict) and ta.get("body_type") == "form" else "json"
    last_exc: Exception | None = None
    resp = None
    for attempt in range(DEFAULT_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                if body_type == "form":
                    resp = client.request(method, url, headers=headers, params=query or None,
                                           data=body if body else None)
                else:
                    resp = client.request(method, url, headers=headers, params=query or None,
                                           json=body if body else None)
                resp.raise_for_status()
            break
        except Exception as e:
            if not _is_retryable(e) or attempt == DEFAULT_MAX_RETRIES:
                raise
            last_exc = e
            delay = DEFAULT_RETRY_BACKOFF * (2 ** attempt)
            log.warning("LLM token 接口失败 (attempt %d/%d): %s, %.1fs 后重试",
                        attempt + 1, DEFAULT_MAX_RETRIES + 1, e, delay)
            time.sleep(delay)
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    extract = str(ta.get("extract") or "").strip()
    if not extract:
        raise RuntimeError("动态 token 未配置 extract（JSONPath）")
    token = _extract_path(data, extract)
    if token is None or str(token) == "":
        raise RuntimeError(f"动态 token 解析失败：extract={extract} 未取到值")
    token = str(token)
    # 写回 llm.api_key（统一：配置中心始终显示当前生效 token）。
    # 用同一 engine 的独立 session 提交，不 commit 传入的 db——否则 _score_case 把
    # 评分 session 传进来时，这次中途 commit 会 expire 掉 cr 等 ORM 对象，冲掉末尾
    # "分数+状态"尚未提交的脏数据，导致分数落库但状态卡在 scoring/executed、随后被
    # 回收重评。取 db.bind 而非全局 SessionLocal：测试用 StaticPool 内存 SQLite，
    # 同一 engine 的新连接仍指向同一内存库，断言可见写回；生产上则是独立 PG 连接。
    try:
        from ...models import Config
        from sqlalchemy.orm import Session
        wdb = Session(bind=db.bind)
        try:
            row = wdb.query(Config).filter(Config.config_key == "llm.api_key").first()
            if row:
                row.config_value = {"value": token}
                wdb.commit()
        finally:
            wdb.close()
    except Exception:  # noqa: BLE001  写回失败不阻塞评分，token 仍可用于本次
        log.exception("写回 llm.api_key 失败（不影响本次调用）")
    r.setex(cache_key, cache_ttl, token)
    log.info("LLM 动态 token 已刷新并缓存 (ttl=%ds, 提前量=%ds)", cache_ttl, REFRESH_AHEAD_SEC)
    return token, {}


def call_llm(config: dict, prompt: str, parse: bool = True) -> dict[str, Any]:
    """调 LLM（OpenAI 兼容 /chat/completions）。

    config: {base_url, api_key, model, max_tokens, timeout, retry_count, retry_backoff,
             auth?, _token?, _token_query?, _db?}
    auth 存在时由调用方先 resolve_llm_token 解析出 _token/_token_query 注入；
    缺省（无 auth）回退旧行为：api_key 放 Authorization: Bearer。
    _db: dynamic 认证下 401 自愈需重取 token 写回，调用方把 DB session 放进 config["_db"]。
    parse=True 时解析评分 JSON（score/reason/brief_comment）；
    parse=False 时只测连通性，返回 {content, usage, latency_sec}。
    失败抛异常。
    """
    base_url = (config.get("base_url") or "").rstrip("/")
    if not base_url:
        raise RuntimeError("LLM base_url 未配置")
    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    query: dict[str, str] = {}
    auth = config.get("auth")
    if auth is not None:
        # 调用方已解析（_token/_token_query 由 resolve_llm_token 注入）
        token = config.get("_token") or ""
        query = dict(config.get("_token_query") or {})
        if token:
            if auth.get("type") == "static":
                # 静态：固定 Authorization: Bearer（resolve 已把 token 设为 "Bearer <api_key>"）
                headers["Authorization"] = token
            else:
                token_in = auth.get("token_in", "header")
                token_name = auth.get("token_name") or "Authorization"
                token_prefix = auth.get("token_prefix") or ""
                if token_in == "query":
                    query[token_name] = f"{token_prefix}{token}".strip()
                else:
                    headers[token_name] = f"{token_prefix}{token}".strip()
    elif config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    body = {
        "model": config.get("model"),
        "max_tokens": int(config.get("max_tokens", 4096)),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "tools": [SCORE_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "submit_score"}},
        "extra_body": {"enable_thinking": False},
    }
    timeout = float(config.get("timeout", 120))
    max_retries = int(config.get("retry_count", DEFAULT_MAX_RETRIES))
    retry_backoff = float(config.get("retry_backoff", DEFAULT_RETRY_BACKOFF))
    start = time.perf_counter()
    last_exc: Exception | None = None
    # 401 自愈：dynamic 认证下若 token 失效（401/403），清缓存重取一次再重试，
    # 覆盖"ttl 配得比真实寿命长 / token 被服务端提前吊销"等边界。
    dynamic_auth = auth is not None and auth.get("type") == "dynamic"
    retried_401 = False
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, params=query or None, json=body)
                resp.raise_for_status()
                data = resp.json()
            break
        except httpx.HTTPStatusError as e:
            if (
                dynamic_auth and not retried_401
                and e.response.status_code in (401, 403)
            ):
                retried_401 = True
                log.warning("LLM 401/403（token 疑似失效），清缓存重取 token 后重试")
                invalidate_llm_token_cache(auth)
                _db = config.get("_db")
                if _db is None:
                    raise  # 无 DB 无法重取，按原错误抛出
                token, query = resolve_llm_token(_db, config)
                config["_token"], config["_token_query"] = token, query
                headers.pop(auth.get("token_name") or "Authorization", None)
                if token:
                    if auth.get("token_in", "header") == "query":
                        query[auth.get("token_name") or "Authorization"] = f"{auth.get('token_prefix') or ''}{token}".strip()
                    else:
                        headers[auth.get("token_name") or "Authorization"] = f"{auth.get('token_prefix') or ''}{token}".strip()
                continue
            if not _is_retryable(e) or attempt == max_retries:
                raise
            last_exc = e
            delay = retry_backoff
            log.warning("LLM call failed (attempt %d/%d): %s, retrying in %.1fs",
                        attempt + 1, max_retries + 1, e, delay)
            time.sleep(delay)
        except Exception as e:
            if not _is_retryable(e) or attempt == max_retries:
                raise
            last_exc = e
            delay = retry_backoff
            log.warning("LLM call failed (attempt %d/%d): %s, retrying in %.1fs",
                        attempt + 1, max_retries + 1, e, delay)
            time.sleep(delay)
    latency = round(time.perf_counter() - start, 3)
    message = data["choices"][0]["message"]
    content = message.get("content") or ""
    usage = data.get("usage") or {}
    if not parse:
        return {
            "content": content,
            "_usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "_latency_sec": latency,
        }
    parsed = _extract_score(message)
    parsed["_usage"] = {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
    parsed["_latency_sec"] = latency
    return parsed


def _extract_score(message: dict[str, Any]) -> dict[str, Any]:
    """从 LLM 响应 message 提取评分 JSON。

    优先取 tool_calls[0].function.arguments（结构化输出，schema 约束）；
    模型/网关未走 tool call 时兜底解析 content 文本。
    """
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        fn = tool_calls[0].get("function") or {}
        arguments = fn.get("arguments")
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str) and arguments.strip():
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                log.warning("tool_call arguments 非合法 JSON，回退 content 解析: %s", arguments[:200])
    return _parse_score(message.get("content") or "")


def _parse_score(content: str) -> dict[str, Any]:
    """从 LLM 输出解析 JSON（容错：剥 markdown 代码块）。"""
    text = (content or "").strip()
    if not text:
        raise ValueError("LLM 返回内容为空，无法解析评分 JSON")
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 兜底：尝试抓第一个 { ... }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise


def _normalize_failure_attribution(raw: Any) -> dict | None:
    """规整 LLM 输出的 failure_attribution，malformed 返回 None。"""
    if not raw or not isinstance(raw, dict):
        return None
    primary = raw.get("primary")
    if not primary or not isinstance(primary, str):
        return None
    items_raw = raw.get("items") or []
    items = []
    if isinstance(items_raw, list):
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            items.append({
                "type": str(it.get("type", "")),
                "label": str(it.get("label", "")),
                "reason": str(it.get("reason", "")),
                "evidence": str(it.get("evidence", "")),
            })
    reason = raw.get("reason")
    return {
        "primary": primary,
        "items": items,
        "reason": reason if isinstance(reason, str) else "",
    }


def score_all_metrics(
    config: dict,
    std_metrics: list[dict],
    extra_metrics: list[dict],
    case: dict,
    agent_output: str,
) -> dict:
    """一次 LLM 调用评所有指标，返回 {
        standard_metrics: [{metric_id, score, reason}],
        extra_metrics: [{metric_id, score, reason}],
        brief_comment, failure_attribution, usage, latency_sec
    }。"""
    prompt = build_score_prompt(std_metrics, extra_metrics, case, agent_output)
    result = call_llm(config, prompt)

    def _clamp(v):
        try:
            return max(0.0, min(100.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    std_out = []
    for m in std_metrics:
        mid = str(m["id"])
        matched = next((x for x in result.get("standard_metrics", []) if str(x.get("metric_id")) == mid), None)
        std_out.append({
            "metric_id": mid,
            "score": _clamp(matched["score"]) if matched else 0.0,
            "reason": (matched.get("reason") or "") if matched else "LLM 未返回该指标评分",
        })

    extra_out = []
    for m in extra_metrics:
        mid = str(m["id"])
        matched = next((x for x in result.get("extra_metrics", []) if str(x.get("metric_id")) == mid), None)
        extra_out.append({
            "metric_id": mid,
            "score": _clamp(matched["score"]) if matched else 0.0,
            "reason": (matched.get("reason") or "") if matched else "LLM 未返回该指标评分",
        })

    brief_comment = result.get("brief_comment") or ""
    if not brief_comment and std_out:
        brief_comment = std_out[0]["reason"]

    return {
        "standard_metrics": std_out,
        "extra_metrics": extra_out,
        "brief_comment": brief_comment,
        "failure_attribution": _normalize_failure_attribution(result.get("failure_attribution")),
        "usage": result.get("_usage", {}),
        "latency_sec": result.get("_latency_sec", 0),
    }

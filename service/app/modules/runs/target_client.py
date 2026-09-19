"""被测 Agent 调用（按流程模板 chain_json 编排 HTTP 请求）。

骨架：支持单 API 直调 + 多步骤串联（extract 提取字段，P22 返回值可选）。
"""
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("target")

MAX_RETRIES = 1
RETRY_BACKOFF = 1.0


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _render(template: str, variables: dict[str, Any]) -> str:
    """简单 {{var}} 占位符替换。"""
    if not isinstance(template, str):
        return template
    for k, v in variables.items():
        k = str(k)
        template = template.replace("{{" + k + "}}", str(v))
        template = template.replace("{{vars." + k + "}}", str(v))
    return template


def _render_obj(obj: Any, variables: dict[str, Any]) -> Any:
    if isinstance(obj, str):
        return _render(obj, variables)
    if isinstance(obj, dict):
        return {k: _render_obj(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render_obj(v, variables) for v in obj]
    return obj


def apply_overrides(chain_json: dict, overrides: dict[str, Any] | None) -> dict:
    """把 overrides（{paramPath: value}）应用到 chain_json 的副本上，返回新 dict。

    paramPath 形态（与前端一致）：
      - vars.<名>            → variables[名]
      - apis[i].<field>      → apis[i][field]（顶层字段，如 url/timeout/retry）
      - apis[i].<obj>.<key>  → apis[i][obj][key]（headers/query/body/auth 等嵌套）
      - steps[i].inputs.<k>  → steps[i].inputs[k]
      - pre_api.<field>      → pre_api[field]（顶层字段，如 url/method/timeout/retry/ttl_seconds）
      - pre_api.<obj>.<key>  → pre_api[obj][key]（headers/query/body/extract 等嵌套）
      - pre_api_groups[i].<k>→ pre_api_groups[i][k]（变量组改值；值为空串 → 删除该键）
      - pre_api_groups       → 整体替换 pre_api_groups（值为 JSON 数组字符串，每个元素 {变量名: 值}）
    无法解析的 path 忽略（不抛错，避免单个非法 path 拖垮整条链路）。
    数值字段（timeout/retry/ttl_seconds）若值为纯数字字符串则转 int。
    """
    import copy
    import json as _json
    import re
    if not overrides:
        return chain_json
    cj = copy.deepcopy(chain_json)

    def _num(v: Any) -> Any:
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            return int(v.strip())
        return v

    for path, value in overrides.items():
        m = re.match(r"^(\w+)\[(\d+)\]\.(.+)$", path)
        if m:
            group, idx, rest = m.group(1), int(m.group(2)), m.group(3)
            arr = cj.get(group) or []
            if not (0 <= idx < len(arr)):
                continue
            item = arr[idx]
            if group == "pre_api_groups":
                # 变量组改值：值恒为字符串（变量名/值语义），空串 → 删除该键
                if value == "":
                    item.pop(rest, None)
                else:
                    item[rest] = value
                continue
            parts = rest.split(".")
            if len(parts) == 1:
                # 顶层字段
                item[parts[0]] = _num(value)
            else:
                # 嵌套：headers.X / query.X / body.X / auth.X
                parent = item.get(parts[0])
                if not isinstance(parent, dict):
                    parent = {}
                    item[parts[0]] = parent
                parent[parts[1]] = value
        elif path.startswith("vars."):
            key = path[len("vars."):]
            variables = cj.setdefault("variables", {})
            variables[key] = value
        elif path == "pre_api_groups":
            # 整体替换变量组：值为 JSON 数组（前端 JSON.stringify 后传字符串），
            # 每个元素须为 {变量名: 值} 对象。解析失败 / 非数组 → 忽略（不抛错）。
            # 已有 key 沿用原值类型（只改值/增删组，不强转字符串）；新 key 用 JSON 解析值。
            g = value
            if isinstance(g, str):
                try:
                    g = _json.loads(g)
                except _json.JSONDecodeError:
                    g = None
            if isinstance(g, list):
                old = cj.get("pre_api_groups") or []
                new_groups = []
                for item in g:
                    if not isinstance(item, dict):
                        continue
                    new_g = {}
                    for k, v in item.items():
                        # 已有 key 且旧组里是数字 → 保留数字类型
                        for og in old:
                            if k in og and isinstance(og[k], (int, float)):
                                new_g[k] = og[k]
                                break
                        else:
                            new_g[k] = v
                    new_groups.append(new_g)
                cj["pre_api_groups"] = new_groups
        elif path.startswith("pre_api_groups."):
            # 新增变量组：单键形态 pre_api_groups.<k>
            key = path[len("pre_api_groups."):]
            if key and value != "":
                cj.setdefault("pre_api_groups", []).append({key: value})
        elif path.startswith("pre_api."):
            rest = path[len("pre_api."):]
            pre = cj.get("pre_api")
            if not isinstance(pre, dict):
                pre = {}
                cj["pre_api"] = pre
            parts = rest.split(".")
            if len(parts) == 1:
                pre[parts[0]] = _num(value)
            elif len(parts) == 2:
                parent = pre.get(parts[0])
                if not isinstance(parent, dict):
                    parent = {}
                    pre[parts[0]] = parent
                if value == "":
                    parent.pop(parts[1], None)
                else:
                    parent[parts[1]] = value
        # 其余未知 path 忽略

    return cj


def call_target(
    chain_json: dict,
    row: dict[str, Any],
    trace: list[dict] | None = None,
    result_extras: dict[str, Any] | None = None,
) -> Any:
    """按 chain_json 执行，返回最终选定输出（extract 提取，P22）。

    chain_json 结构（沿用 apiChain）：
      { "apis": [{id, method, url, headers, query, body, timeout, retry, extract, extract_to_result}],
        "steps": [{api_id, inputs}], "variables": {...},
        "final_extract": <见下> }
    row: 数据集一行的变量（用例编号/测试输入/预期结果/维度/case_id…）。

    api.extract_to_result（可选）：{字段名: JSONPath}，从本步响应提取字段写入
    result_extras（供 worker 回写 case_results 的 node_id/trace_no 等执行关联凭证）。
    与 extract（写回 variables 供后续步骤）不同，extract_to_result 不进变量、只收集。

    final_extract 两种形态：
      - string（兼容旧）：JSONPath，从最后一步响应提取单字段，返回该字段值。
      - dict（新，跨步骤多字段）：{字段名: {step: 步骤序号(0-based), path: JSONPath}}，
        返回 {字段名: 提取值} 的 dict；step 缺省 = 最后一步。
    未定义 final_extract：返回最后一步响应（str 原样，其他 JSON 序列化）。
    """
    variables: dict[str, Any] = dict(row)
    variables.update(chain_json.get("variables", {}))

    apis = {a["id"]: a for a in chain_json.get("apis", [])}
    steps = chain_json.get("steps", [])
    if not steps:
        # 无步骤：若有单 api 则直调
        if len(apis) == 1:
            steps = [{"api_id": next(iter(apis)), "inputs": {}}]
        else:
            raise ValueError("流程模板无执行步骤且无单一 API")

    last_output: Any = None
    step_outputs: list[Any] = []  # 每步响应，供 final_extract 跨步骤提取
    with httpx.Client(timeout=60) as client:
        for step in steps:
            api = apis[step["api_id"]]
            inputs = _render_obj(step.get("inputs", {}), variables)
            # inputs 可覆盖 url/query/body
            url = _render(api.get("url", ""), variables)
            headers = _render_obj(api.get("headers", {}), variables)
            query = _render_obj(api.get("query", {}), variables)
            body = _render_obj(api.get("body", {}), variables)
            method = api.get("method", "POST").upper()

            # body 渲染后若仍是 str（chain_json 里 body 配成了 JSON 字符串），
            # 尝试解析成对象，避免 **str 报 'str' object is not a mapping。
            if isinstance(body, str):
                import json as _json
                try:
                    body = _json.loads(body)
                except _json.JSONDecodeError:
                    body = {"_raw": body}  # 非 JSON 字符串，包一层避免崩

            merged_body = {**(body or {}), **inputs} if method in ("POST", "PUT", "PATCH") else body
            body_type = api.get("body_type", "json")
            last_exc: Exception | None = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    if body_type == "form":
                        # urlencoded 表单：data=dict → application/x-www-form-urlencoded
                        resp = client.request(
                            method, url, headers=headers, params=query or None,
                            data=merged_body if merged_body else None,
                        )
                    else:
                        resp = client.request(
                            method, url, headers=headers, params=query or None,
                            json=merged_body if merged_body else None,
                        )
                    resp.raise_for_status()
                    break
                except Exception as e:
                    if not _is_retryable(e) or attempt == MAX_RETRIES:
                        # 失败也记录 trace（含状态码/错误），便于自检定位
                        if trace is not None:
                            trace.append({
                                "api_id": step["api_id"], "method": method, "url": url,
                                "headers": headers, "query": query, "body": merged_body,
                                "status": getattr(getattr(e, "response", None), "status_code", None),
                                "error": str(e), "response": None,
                            })
                        raise
                    last_exc = e
                    delay = RETRY_BACKOFF * (2 ** attempt)
                    log.warning("Target call failed (attempt %d/%d): %s, retrying in %.1fs",
                                attempt + 1, MAX_RETRIES + 1, e, delay)
                    time.sleep(delay)
            try:
                last_output = resp.json()
            except Exception:
                last_output = resp.text
            step_outputs.append(last_output)
            if trace is not None:
                trace.append({
                    "api_id": step["api_id"], "method": method, "url": url,
                    "headers": headers, "query": query, "body": merged_body,
                    "status": resp.status_code, "error": None, "response": last_output,
                })
            # extract: 从响应提取选定字段（P22），写回 variables 供后续步骤
            extract = api.get("extract") or {}
            step_id = step.get("id") or step["api_id"]
            for var_name, json_path in extract.items():
                val = _extract_path(last_output, json_path)
                variables[var_name] = val
                # 同时注册 steps.<step_id>.<var_name>，供前端占位符面板的
                # {{steps.s1.reply}} 形式引用（_render 做扁平键替换，键名整体匹配）
                variables[f"steps.{step_id}.{var_name}"] = val
            variables[f"steps.{step_id}.status_code"] = resp.status_code
            variables[f"steps.{step_id}.body"] = last_output
            variables["last_response"] = last_output
            # extract_to_result: 从本步响应提取字段收集到 result_extras（供 worker 回写 case_results）
            extract_to_result = api.get("extract_to_result") or {}
            if extract_to_result and result_extras is not None:
                for field_name, json_path in extract_to_result.items():
                    result_extras[field_name] = _extract_path(last_output, json_path)

    # 最终返回：按 final_extract 形态提取
    final_extract = chain_json.get("final_extract")
    if final_extract:
        if isinstance(final_extract, str):
            # 兼容旧：单路径，从最后一步响应提取
            return _extract_path(last_output, final_extract)
        if isinstance(final_extract, dict):
            # 新：跨步骤多字段
            last_idx = len(step_outputs) - 1
            result: dict[str, Any] = {}
            for field_name, spec in final_extract.items():
                if not isinstance(spec, dict):
                    raise ValueError(f"final_extract[{field_name}] 必须是 {{step, path}} 对象")
                idx = spec.get("step", last_idx)
                path = spec.get("path", "")
                if not isinstance(idx, int) or idx < 0 or idx >= len(step_outputs):
                    raise ValueError(f"final_extract[{field_name}].step={idx} 超出步骤范围 [0, {last_idx}]")
                if not path:
                    raise ValueError(f"final_extract[{field_name}].path 不能为空")
                result[field_name] = _extract_path(step_outputs[idx], path)
            return result
        raise ValueError("final_extract 必须是 string 或 dict")
    return last_output if isinstance(last_output, str) else _to_text(last_output)


def _extract_path(obj: Any, path: str) -> Any:
    """极简 JSONPath：a.b.c / a[0].b，兼容 $. 前缀（$.a.b.c）。"""
    path = path.strip()
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


def _to_text(obj: Any) -> str:
    """非 str 对象序列化为 JSON 文本；str 原样返回。"""
    if isinstance(obj, str):
        return obj
    import json
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def split_user_input(user_input: str) -> list[str]:
    """把 user_input 拆成多轮。

    规则：先按换行（\\n / \\r\\n）切，再对每段按 ' → '（前后带空格，全角/半角箭头）切。
    合并后 strip，丢弃空串。返回轮次列表；空输入返回 ['']。
    """
    import re
    if not user_input:
        return [""]
    # 先按换行切
    lines = re.split(r"\r?\n", user_input)
    turns: list[str] = []
    for line in lines:
        # 再按带空格的箭头切（半角 → 和全角 →）
        parts = re.split(r"\s+→\s+|\s+→\s+", line)
        for p in parts:
            p = p.strip()
            if p:
                turns.append(p)
    return turns if turns else [""]


def call_pre_api(
    pre_api: dict[str, Any],
    variables: dict[str, Any] | None = None,
    trace: list[dict] | None = None,
) -> Any:
    """调用前置 API（获取 session 等），返回响应 JSON。

    pre_api 结构（与 chain_json.apis[i] 类似，但不含 extract_to_result）：
      { "method": "POST", "url": "...", "headers": {}, "body": {},
        "body_type": "json"|"form", "timeout": 60, "retry": 3 }

    body_type:
      - "json"（默认）：JSON body
      - "form"：urlencoded 表单（data=dict）

    variables: 用于渲染 url/headers/query/body 中的 {{var}} 占位符。
    trace: 传入 list 时记录请求/响应（自检定位用）。
    """
    import json as _json

    method = pre_api.get("method", "POST").upper()
    url = _render(pre_api.get("url", ""), variables or {})
    headers = _render_obj(pre_api.get("headers", {}), variables or {})
    query = _render_obj(pre_api.get("query", {}), variables or {})
    body = _render_obj(pre_api.get("body", {}), variables or {})
    body_type = pre_api.get("body_type", "json")
    timeout = pre_api.get("timeout", 60)
    retry = pre_api.get("retry", MAX_RETRIES)

    if body_type == "json" and isinstance(body, str):
        try:
            body = _json.loads(body)
        except _json.JSONDecodeError:
            body = {"_raw": body}

    last_exc: Exception | None = None
    with httpx.Client(timeout=timeout) as client:
        for attempt in range(retry + 1):
            try:
                if body_type == "form":
                    resp = client.request(
                        method, url, headers=headers, params=query or None,
                        data=body if body else None,
                    )
                else:
                    resp = client.request(
                        method, url, headers=headers, params=query or None,
                        json=body if body else None,
                    )
                resp.raise_for_status()
                break
            except Exception as e:
                if not _is_retryable(e) or attempt == retry:
                    if trace is not None:
                        trace.append({
                            "api_id": "pre_api", "method": method, "url": url,
                            "headers": headers, "query": query, "body": body,
                            "status": getattr(getattr(e, "response", None), "status_code", None),
                            "error": str(e), "response": None,
                        })
                    raise
                last_exc = e
                delay = RETRY_BACKOFF * (2 ** attempt)
                log.warning("Pre-API call failed (attempt %d/%d): %s, retrying in %.1fs",
                            attempt + 1, retry + 1, e, delay)
                time.sleep(delay)
        try:
            output = resp.json()
        except Exception:
            output = resp.text
        if trace is not None:
            trace.append({
                "api_id": "pre_api", "method": method, "url": url,
                "headers": headers, "query": query, "body": body,
                "status": resp.status_code, "error": None, "response": output,
            })
        return output


def pre_api_enabled(chain_json: dict[str, Any] | None) -> bool:
    """前置 API 是否应执行（v1.5）。

    仅当 pre_api 存在、enabled 显式为 true、且 url 非空时才执行。
    - enabled 缺省/false → 不执行（与前端「默认不勾选」一致）
    - url 为空 → 视为未配置，不执行（避免空 URL 请求把 case 打成 error）
    """
    if not chain_json:
        return False
    pre_api = chain_json.get("pre_api")
    if not pre_api or not isinstance(pre_api, dict):
        return False
    if pre_api.get("enabled") is not True:
        return False
    return bool(str(pre_api.get("url") or "").strip())


def get_group_variables(
    run_id: str,
    round_no: int,
    chain_json: dict[str, Any],
    r: Any,
    trace: list[dict] | None = None,
) -> dict[str, Any]:
    """获取组级变量（session 缓存 + 变量组循环）。

    1. 从 chain_json 读 pre_api 和 pre_api_groups
    2. 按 round_no % len(pre_api_groups) 选变量组
    3. 变量组覆盖模板 variables 中的同名变量
    4. 查 Redis 缓存 key = agent_eval:session:{run_id}:{round_no}
    5. 命中 → 直接返回
    6. 未命中 → 调前置 API（用组变量渲染）→ JSONPath 提取 → 写 Redis（带 TTL）→ 返回
    7. 前置 API 未配置 → 返回空 dict

    返回的 dict 包含：
    - 变量组的原始变量（phone, device_id, password 等）
    - 前置 API 提取的变量（session_id 等）
    后续用例通过 {{var}} 占位符引用这些变量。
    """
    import json as _json

    enabled = pre_api_enabled(chain_json)
    pre_api = chain_json.get("pre_api") if enabled else None
    pre_api_groups = (chain_json.get("pre_api_groups") or []) if enabled else []
    template_vars = chain_json.get("variables") or {}

    if not pre_api and not pre_api_groups:
        return {}

    # 选变量组（循环）
    group_vars: dict[str, Any] = {}
    if pre_api_groups:
        group_idx = round_no % len(pre_api_groups)
        group_vars = dict(pre_api_groups[group_idx])
        log.info("round %d using variable group %d/%d: %s",
                 round_no, group_idx, len(pre_api_groups), list(group_vars.keys()))

    # 合并：模板变量 < 组变量（组变量覆盖模板）
    merged_vars = {**template_vars, **group_vars}

    cache_key = f"agent_eval:session:{run_id}:{round_no}"
    cached = r.get(cache_key)
    if cached:
        log.info("session cache hit: %s", cache_key)
        # 缓存里存的是 {group_vars, extracted_vars}
        cached_data = _json.loads(cached)
        return {**cached_data.get("group", {}), **cached_data.get("extracted", {})}

    # 缓存未命中，调前置 API
    extracted: dict[str, Any] = {}
    if pre_api:
        output = call_pre_api(pre_api, variables=merged_vars, trace=trace)
        extract = pre_api.get("extract") or {}
        for var_name, json_path in extract.items():
            extracted[var_name] = _extract_path(output, json_path)

    ttl = int(pre_api.get("ttl_seconds", 3600)) if pre_api else 3600
    cache_value = _json.dumps({
        "group": group_vars,
        "extracted": extracted,
    }, ensure_ascii=False)
    r.setex(cache_key, ttl, cache_value)
    log.info("session cache set: %s (ttl=%ds, group=%s, extracted=%s)",
             cache_key, ttl, list(group_vars.keys()), list(extracted.keys()))

    return {**group_vars, **extracted}


def ensure_session(
    run_id: str,
    scope_key: int | str,
    chain_json: dict[str, Any],
    r: Any,
    refresh_threshold_sec: int = 60,
    trace: list[dict] | None = None,
) -> dict[str, Any]:
    """确保 session 有效（检查 TTL，快过期时自动刷新）。

    scope_key:
      - int (round_no)：轮次模式，每轮独立 session，变量组按 round_no % len(groups) 循环
      - "global"：无轮次且无变量组，所有 case 共享一个 session
      - 其他 str（如 "case:0"）：非轮次但有变量组，按组号独立 session（见 ensure_case_session）

    1. 查 Redis 缓存 + TTL
    2. 缓存不存在 → 调前置 API 获取新 session
    3. 缓存存在但剩余 TTL < refresh_threshold_sec → 调前置 API 刷新
    4. 缓存存在且 TTL 充足 → 直接返回
    """
    import json as _json

    pre_api = chain_json.get("pre_api")
    if not pre_api_enabled(chain_json):
        return {}

    cache_key = f"agent_eval:session:{run_id}:{scope_key}"
    cached = r.get(cache_key)
    ttl_remaining = r.ttl(cache_key) if cached else -2

    if cached and ttl_remaining > refresh_threshold_sec:
        log.info("session valid: %s (ttl_remaining=%ds)", cache_key, ttl_remaining)
        cached_data = _json.loads(cached)
        return {**cached_data.get("group", {}), **cached_data.get("extracted", {})}

    # 需要刷新（缓存不存在或快过期）
    if cached:
        log.info("session expiring soon: %s (ttl_remaining=%ds < %ds), refreshing",
                 cache_key, ttl_remaining, refresh_threshold_sec)
    else:
        log.info("session not found: %s, fetching", cache_key)

    # 重新调前置 API
    pre_api_groups = chain_json.get("pre_api_groups") or []
    template_vars = chain_json.get("variables") or {}
    group_vars: dict[str, Any] = {}
    if pre_api_groups and scope_key != "global":
        # 轮次模式（int round_no）/ 非轮次带变量组（"case:<组号>"）：按组号选变量组
        group_idx = scope_key % len(pre_api_groups) if isinstance(scope_key, int) else int(scope_key.rsplit(":", 1)[1])
        group_vars = dict(pre_api_groups[group_idx])
    # scope_key="global"（无变量组）：只用模板变量
    merged_vars = {**template_vars, **group_vars}

    output = call_pre_api(pre_api, variables=merged_vars, trace=trace)
    extract = pre_api.get("extract") or {}
    extracted: dict[str, Any] = {}
    for var_name, json_path in extract.items():
        extracted[var_name] = _extract_path(output, json_path)

    ttl = int(pre_api.get("ttl_seconds", 3600))
    cache_value = _json.dumps({
        "group": group_vars,
        "extracted": extracted,
    }, ensure_ascii=False)
    r.setex(cache_key, ttl, cache_value)
    log.info("session refreshed: %s (ttl=%ds)", cache_key, ttl)

    return {**group_vars, **extracted}


def ensure_case_session(
    run_id: str,
    sort_order: int,
    chain_json: dict[str, Any],
    r: Any,
    refresh_threshold_sec: int = 60,
    trace: list[dict] | None = None,
) -> dict[str, Any]:
    """非轮次模式取组变量 + session（变量组与轮次解耦，v1.6）。

    - 有变量组：group_idx = sort_order % len(groups)，每组独立 session 缓存
      （cache key 带组号 "case:<idx>"），同组 case 共享、跨组不串号。
    - 无变量组：退化为 "global"，所有 case 共享一个 session（原行为）。
    前置 API 未启用时返回 {}。
    """
    if not pre_api_enabled(chain_json):
        return {}
    groups = chain_json.get("pre_api_groups") or []
    if groups:
        group_idx = sort_order % len(groups)
        scope_key = f"case:{group_idx}"
    else:
        scope_key = "global"
    return ensure_session(run_id, scope_key, chain_json, r,
                          refresh_threshold_sec=refresh_threshold_sec, trace=trace)


def call_target_multi_turn(
    chain_json: dict,
    row: dict[str, Any],
    limit_key: str | None = None,
    limit_value: int = 0,
    r: Any = None,
    trace: list[dict] | None = None,
    result_extras: dict[str, Any] | None = None,
) -> str:
    """多轮调用被测 Agent，返回拼接文本。

    1. turns = split_user_input(row['user_input'])
    2. 若 len(turns) == 1：直接 call_target(chain_json, row) 返回（单轮退化，与现状一致）
    3. 否则：逐轮调 call_target（替换 row['user_input']），每轮可选限流
    4. 拼接：'Q{i}: {turn}\\nA{i}: {out_text}' 用 '\\n' 连接

    trace: 传入 list 时，逐步记录每步请求/响应（自检定位用）。
    result_extras: 传入 dict 时，收集各步 api.extract_to_result 提取的字段
    （多轮时取最后一轮的提取值，覆盖前几轮）。
    """
    from .worker import SlotBusy, _acquire_limit, _release_limit

    def _acquire() -> None:
        """抢被测并发槽位（请求级，每轮独立）。抢不到抛 SlotBusy 让出，不 sleep。"""
        if limit_key is None or r is None:
            return
        if not _acquire_limit(r, limit_key, limit_value):
            raise SlotBusy("被测 Agent 并发槽位忙")

    def _release() -> None:
        if limit_key is None or r is None:
            return
        _release_limit(r, limit_key)

    turns = split_user_input(row.get("user_input", ""))
    if len(turns) == 1:
        # 单轮也限流（请求级并发上限），与多轮一致
        _acquire()
        try:
            out = call_target(chain_json, row, trace=trace, result_extras=result_extras)
        finally:
            _release()
        return _to_text(out)

    lines: list[str] = []
    for i, turn in enumerate(turns, 1):
        row_copy = dict(row)
        row_copy["user_input"] = turn
        _acquire()
        try:
            out = call_target(chain_json, row_copy, trace=trace, result_extras=result_extras)
        finally:
            _release()
        out_text = _to_text(out)
        lines.append(f"Q{i}: {turn}")
        lines.append(f"A{i}: {out_text}")
    return "\n".join(lines)

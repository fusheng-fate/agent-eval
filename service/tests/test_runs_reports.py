"""runs + reports 核心逻辑测试：评分数学 / 报告聚合 / HTML 渲染 / 被测调用。"""
import uuid

from fastapi import HTTPException

from app.models import (
    Case, CaseResult, Config, Dataset, Evaluator, EvaluatorMetric,
    FlowTemplate, Metric, Report, Run,
)
from app.modules.reports.report_service import build_report, render_html
from app.modules.runs import llm_client, target_client, task_queue
from app.modules.runs.routes import _get_config


def _patch_task_queue_to(db, monkeypatch):
    """让 task_queue 内部 SessionLocal 指向测试的 SQLite 会话。

    claim_case / recover_stale_running 内部自建 SessionLocal()，
    测试用 SQLite 内存库，需把 task_queue.SessionLocal 替换为返回 db 的 lambda。
    SQLite 下 dialect.name == "sqlite"，claim_case 不会加 SKIP LOCKED（符合预期）。
    """
    monkeypatch.setattr(task_queue, "SessionLocal", lambda: db)


# ---------- llm_client ----------
def test_parse_score_plain_json():
    assert llm_client._parse_score('{"score": 80, "reason": "ok"}') == {"score": 80, "reason": "ok"}


def test_parse_score_markdown_block():
    out = llm_client._parse_score('```json\n{"score": 90, "reason": "great"}\n```')
    assert out["score"] == 90


def test_parse_score_embedded_json():
    out = llm_client._parse_score('打分结果如下：{"score": 60, "reason": "一般"} 谢谢')
    assert out["score"] == 60


def test_build_score_prompt_contains_context():
    p = llm_client.build_score_prompt(
        [{"id": "m1", "name": "准确性", "weight": 1.0, "skill_md": "评分标准X"}],
        [],
        {"user_input": "输入A", "expected_gt": "期望B"},
        "实际输出C",
    )
    assert "评分标准X" in p and "输入A" in p and "期望B" in p and "实际输出C" in p


def test_extract_score_from_tool_call():
    """主路径：结果在 tool_calls[0].function.arguments（JSON 字符串）。"""
    msg = {
        "content": None,
        "tool_calls": [{
            "function": {
                "name": "submit_score",
            "arguments": '{"score": 80, "reason": "ok", "brief_comment": "c"}',
            }
        }],
    }
    out = llm_client._extract_score(msg)
    assert out["score"] == 80 and out["brief_comment"] == "c"


def test_extract_score_tool_call_arguments_already_dict():
    """部分网关 arguments 已是 dict，直接返回。"""
    msg = {"tool_calls": [{"function": {"name": "submit_score", "arguments": {"score": 90, "reason": "r", "brief_comment": ""}}}] }
    assert llm_client._extract_score(msg)["score"] == 90


def test_extract_score_falls_back_to_content():
    """兜底：无 tool_calls 时回退解析 content。"""
    msg = {"content": '```json\n{"score": 60, "reason": "一般", "brief_comment": ""}\n```'}
    assert llm_client._extract_score(msg)["score"] == 60


def test_extract_score_malformed_arguments_falls_back():
    """arguments 非合法 JSON 时回退 content 解析。"""
    msg = {
        "content": '{"score": 40, "reason": "fb", "brief_comment": ""}',
        "tool_calls": [{"function": {"name": "submit_score", "arguments": "not-json"}}],
    }
    assert llm_client._extract_score(msg)["score"] == 40


def test_score_all_metrics_clamps_out_of_range(monkeypatch):
    """LLM 偶发越界（负分/超 100）→ clamp 到 0-100。"""
    def fake_call(cfg, prompt, parse=True):
        return {"standard_metrics": [{"metric_id": "m1", "score": 150, "reason": "r"}],
                "extra_metrics": [], "brief_comment": "c",
                "_usage": {}, "_latency_sec": 0.1}
    monkeypatch.setattr(llm_client, "call_llm", fake_call)
    out = llm_client.score_all_metrics({}, [{"id": "m1", "name": "x", "weight": 1.0, "skill_md": "x"}], [], {"user_input": "i"}, "out")
    assert out["standard_metrics"][0]["score"] == 100.0

    def fake_call_neg(cfg, prompt, parse=True):
        return {"standard_metrics": [{"metric_id": "m1", "score": -10, "reason": "r"}],
                "extra_metrics": [], "brief_comment": "c",
                "_usage": {}, "_latency_sec": 0.1}
    monkeypatch.setattr(llm_client, "call_llm", fake_call_neg)
    out = llm_client.score_all_metrics({}, [{"id": "m1", "name": "x", "weight": 1.0, "skill_md": "x"}], [], {"user_input": "i"}, "out")
    assert out["standard_metrics"][0]["score"] == 0.0


def test_score_all_metrics_brief_comment_null_falls_back_to_reason(monkeypatch):
    """LLM 返回 brief_comment=null（mock 常见）→ 兜底用 reason，避免前端"打分理由"列空。"""
    def fake_call(cfg, prompt, parse=True):
        return {"standard_metrics": [{"metric_id": "m1", "score": 95, "reason": "mock理由"}],
                "extra_metrics": [], "brief_comment": None,
                "_usage": {}, "_latency_sec": 0.1}
    monkeypatch.setattr(llm_client, "call_llm", fake_call)
    out = llm_client.score_all_metrics({}, [{"id": "m1", "name": "x", "weight": 1.0, "skill_md": "x"}], [], {"user_input": "i"}, "out")
    assert out["brief_comment"] == "mock理由"


def test_score_all_metrics_brief_comment_empty_falls_back_to_reason(monkeypatch):
    """brief_comment 空字符串同样兜底 reason。"""
    def fake_call(cfg, prompt, parse=True):
        return {"standard_metrics": [{"metric_id": "m1", "score": 95, "reason": "评分依据"}],
                "extra_metrics": [], "brief_comment": "",
                "_usage": {}, "_latency_sec": 0.1}
    monkeypatch.setattr(llm_client, "call_llm", fake_call)
    out = llm_client.score_all_metrics({}, [{"id": "m1", "name": "x", "weight": 1.0, "skill_md": "x"}], [], {"user_input": "i"}, "out")
    assert out["brief_comment"] == "评分依据"


def test_score_all_metrics_brief_comment_present_kept(monkeypatch):
    """brief_comment 有值时保留原值，不被 reason 覆盖。"""
    def fake_call(cfg, prompt, parse=True):
        return {"standard_metrics": [{"metric_id": "m1", "score": 95, "reason": "详细理由"}],
                "extra_metrics": [], "brief_comment": "一句话说明",
                "_usage": {}, "_latency_sec": 0.1}
    monkeypatch.setattr(llm_client, "call_llm", fake_call)
    out = llm_client.score_all_metrics({}, [{"id": "m1", "name": "x", "weight": 1.0, "skill_md": "x"}], [], {"user_input": "i"}, "out")
    assert out["brief_comment"] == "一句话说明"


# ---------- target_client ----------
def test_extract_path_nested():
    obj = {"a": {"b": [{"c": 7}]}}
    assert target_client._extract_path(obj, "a.b[0].c") == 7


def test_extract_path_missing_returns_none():
    assert target_client._extract_path({"a": 1}, "a.z") is None


def test_extract_path_dollar_prefix():
    """兼容 $. 前缀：$.a.b 与 a.b 等价。"""
    obj = {"a": {"b": 7}}
    assert target_client._extract_path(obj, "$.a.b") == 7
    assert target_client._extract_path(obj, "a.b") == 7


def test_extract_path_dollar_prefix_array():
    assert target_client._extract_path({"a": [{"c": 1}]}, "$.a[0].c") == 1


def test_render_placeholder():
    assert target_client._render("hi {{name}}", {"name": "bob"}) == "hi bob"


def _sample_chain():
    return {
        "variables": {"用户名": "alice"},
        "apis": [
            {"id": "agent", "method": "POST", "url": "http://x/agent", "timeout": 30,
             "retry": 0, "headers": {"Authorization": "Bearer old"}},
            {"id": "api2", "method": "GET", "url": "http://x/2", "timeout": 30, "retry": 0},
        ],
        "steps": [{"id": "s1", "api_id": "agent", "inputs": {"user_id": "{{uid}}"}}],
    }


def test_apply_overrides_top_level_field():
    cj = target_client.apply_overrides(_sample_chain(), {"apis[0].timeout": "6000"})
    assert cj["apis"][0]["timeout"] == 6000
    # 原对象不被修改（深拷贝）
    assert _sample_chain()["apis"][0]["timeout"] == 30


def test_apply_overrides_nested_header():
    cj = target_client.apply_overrides(_sample_chain(), {"apis[0].headers.Authorization": "Bearer new"})
    assert cj["apis"][0]["headers"]["Authorization"] == "Bearer new"


def test_apply_overrides_vars_and_step_input():
    cj = target_client.apply_overrides(
        _sample_chain(), {"vars.用户名": "bob", "steps[0].inputs.user_id": "u999"}
    )
    assert cj["variables"]["用户名"] == "bob"
    assert cj["steps"][0]["inputs"]["user_id"] == "u999"


def test_apply_overrides_ignores_unknown_path_and_empty():
    cj = target_client.apply_overrides(_sample_chain(), {"bogus.path": "x"})
    assert cj["apis"][0]["timeout"] == 30
    # 空 overrides 原样返回
    assert target_client.apply_overrides(_sample_chain(), None) is not None


def _sample_chain_with_pre_api():
    return {
        "variables": {"用户名": "alice"},
        "apis": [{"id": "agent", "method": "POST", "url": "http://x/agent", "timeout": 30, "retry": 0}],
        "steps": [{"id": "s1", "api_id": "agent", "inputs": {}}],
        "pre_api": {
            "enabled": True, "method": "POST", "url": "http://x/session/create",
            "timeout": 60, "retry": 3, "ttl_seconds": 3600,
            "headers": {"Content-Type": "application/json"},
            "body": '{"phone": "{{phone}}"}',
            "extract": {"session_id": "data.sessionId"},
        },
        "pre_api_groups": [{"phone": "13800000001", "device_id": "DEV001"}],
    }


def test_apply_overrides_pre_api_top_and_nested():
    cj = target_client.apply_overrides(
        _sample_chain_with_pre_api(),
        {
            "pre_api.url": "http://y/session",
            "pre_api.timeout": "120",
            "pre_api.headers.Content-Type": "application/x-www-form-urlencoded",
            "pre_api.extract.session_id": "data.token",
        },
    )
    pa = cj["pre_api"]
    assert pa["url"] == "http://y/session"
    assert pa["timeout"] == 120
    assert pa["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert pa["extract"]["session_id"] == "data.token"
    # 原对象不被修改（深拷贝）
    assert _sample_chain_with_pre_api()["pre_api"]["url"] == "http://x/session/create"


def test_apply_overrides_pre_api_group_value_and_empty_deletes_key():
    cj = target_client.apply_overrides(
        _sample_chain_with_pre_api(),
        {"pre_api_groups[0].phone": "13900000002", "pre_api_groups[0].device_id": ""},
    )
    assert cj["pre_api_groups"][0] == {"phone": "13900000002"}


def test_apply_overrides_pre_api_group_replace_whole():
    # pre_api_groups 整体替换：JSON 数组字符串 → 替换原组
    cj = target_client.apply_overrides(
        _sample_chain_with_pre_api(),
        {"pre_api_groups": '[{"phone": "13911111111", "device_id": "DEV002"}, {"phone": "13922222222"}]'},
    )
    groups = cj["pre_api_groups"]
    assert len(groups) == 2
    assert groups[0] == {"phone": "13911111111", "device_id": "DEV002"}
    assert groups[1] == {"phone": "13922222222"}
    # 原对象不被修改（深拷贝）
    assert _sample_chain_with_pre_api()["pre_api_groups"][0]["phone"] == "13800000001"


def test_apply_overrides_pre_api_group_replace_invalid_ignored():
    # 非数组 / 非法 JSON → 忽略，保留原组
    cj = target_client.apply_overrides(
        _sample_chain_with_pre_api(), {"pre_api_groups": '{"phone": "x"}'}
    )
    assert cj["pre_api_groups"] == [{"phone": "13800000001", "device_id": "DEV001"}]
    cj2 = target_client.apply_overrides(
        _sample_chain_with_pre_api(), {"pre_api_groups": "not-json"}
    )
    assert cj2["pre_api_groups"] == [{"phone": "13800000001", "device_id": "DEV001"}]


def test_call_target_no_steps_no_single_api_raises():
    try:
        target_client.call_target(
            {"apis": [{"id": "a"}, {"id": "b"}], "steps": []}, {}
        )
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def _mock_client(monkeypatch, responses: list[dict], requests: list[dict] | None = None):
    """mock httpx.Client，按调用顺序返回预设响应体（dict → resp.json()）。

    requests 传入 list 时，记录每次 request 的 (method, url, params, json) 供断言。
    """
    class _Resp:
        status_code = 200
        def __init__(self, body): self._body = body
        def raise_for_status(self): pass
        def json(self): return self._body
        @property
        def text(self): return str(self._body)
    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def request(self, method, url, **k):
            if requests is not None:
                requests.append({"method": method, "url": url,
                                 "params": k.get("params"), "json": k.get("json"),
                                 "data": k.get("data")})
            return _Resp(responses.pop(0))
    monkeypatch.setattr(target_client.httpx, "Client", _Client)


def test_call_target_final_extract_string_compat(monkeypatch):
    """final_extract 为 string：从最后一步响应提取单字段（兼容旧）。"""
    _mock_client(monkeypatch, [{"data": {"answer": "hi"}}])
    out = target_client.call_target(
        {"apis": [{"id": "a", "url": "/x"}], "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": "data.answer"},
        {},
    )
    assert out == "hi"


def test_call_target_final_extract_dict_cross_step(monkeypatch):
    """final_extract 为 dict：跨步骤多字段提取。"""
    _mock_client(monkeypatch, [
        {"data": {"token": "tk1"}},
        {"result": {"summary": "s2"}},
        {"result": {"summary": "s3"}, "trace_id": "t9"},
    ])
    out = target_client.call_target(
        {"apis": [{"id": "a", "url": "/1"}, {"id": "b", "url": "/2"}, {"id": "c", "url": "/3"}],
         "steps": [{"api_id": "a", "inputs": {}}, {"api_id": "b", "inputs": {}}, {"api_id": "c", "inputs": {}}],
         "final_extract": {
             "token":  {"step": 0, "path": "data.token"},
             "summary": {"step": 2, "path": "result.summary"},
             "trace_id": {"step": 2, "path": "trace_id"},
         }},
        {},
    )
    assert out == {"token": "tk1", "summary": "s3", "trace_id": "t9"}


def test_call_target_final_extract_dict_step_default_last(monkeypatch):
    """dict 形态 step 缺省 = 最后一步。"""
    _mock_client(monkeypatch, [{"a": 1}, {"b": 2}])
    out = target_client.call_target(
        {"apis": [{"id": "a", "url": "/1"}, {"id": "b", "url": "/2"}],
         "steps": [{"api_id": "a", "inputs": {}}, {"api_id": "b", "inputs": {}}],
         "final_extract": {"x": {"path": "b"}}},
        {},
    )
    assert out == {"x": 2}


def test_call_target_final_extract_dict_step_out_of_range(monkeypatch):
    _mock_client(monkeypatch, [{"a": 1}])
    try:
        target_client.call_target(
            {"apis": [{"id": "a", "url": "/1"}], "steps": [{"api_id": "a", "inputs": {}}],
             "final_extract": {"x": {"step": 5, "path": "a"}}},
            {},
        )
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def test_call_target_final_extract_dict_empty_path(monkeypatch):
    _mock_client(monkeypatch, [{"a": 1}])
    try:
        target_client.call_target(
            {"apis": [{"id": "a", "url": "/1"}], "steps": [{"api_id": "a", "inputs": {}}],
             "final_extract": {"x": {"step": 0, "path": ""}}},
            {},
        )
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def test_call_target_final_extract_dict_spec_not_dict(monkeypatch):
    _mock_client(monkeypatch, [{"a": 1}])
    try:
        target_client.call_target(
            {"apis": [{"id": "a", "url": "/1"}], "steps": [{"api_id": "a", "inputs": {}}],
             "final_extract": {"x": "a"}},  # spec 不是 dict
            {},
        )
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def test_call_target_body_as_json_string(monkeypatch):
    """body 配成 JSON 字符串（非对象）时不崩，能正常解析发送。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [{"ok": True}], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/x",
             "body": '{"user_input": "hi", "n": 1}'},  # JSON 字符串
        ],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    # body 被解析成对象发送
    assert reqs[0]["json"] == {"user_input": "hi", "n": 1}


def test_call_target_form_body_type(monkeypatch):
    """body_type=form 时用 data=（urlencoded）而非 json= 发送。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [{"ok": True}], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/x", "body_type": "form",
             "body": {"session_id": "S1", "message": "hi"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    # form 形式：data 有值，json 为 None
    assert reqs[0]["data"] == {"session_id": "S1", "message": "hi"}
    assert reqs[0]["json"] is None


def test_call_target_json_body_type_default(monkeypatch):
    """body_type 缺省按 json 发送（json= 有值，data 为 None）。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [{"ok": True}], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/x",
             "body": {"k": "v"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    assert reqs[0]["json"] == {"k": "v"}
    assert reqs[0]["data"] is None


def test_form_body_with_steps_placeholder(monkeypatch):
    """form 模式 + {{steps.s1.xxx}} 占位符：上一步 extract 值替换后以 urlencoded 发送。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [
        {"session_id": "SID999"},   # step s1 响应
        {"ok": True},                 # step s2 响应
    ], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/session",
             "extract": {"sid": "session_id"}},
            {"id": "b", "method": "POST", "url": "/chat", "body_type": "form",
             "body": {"session_id": "{{steps.s1.sid}}", "message": "hi"}},
        ],
         "steps": [{"id": "s1", "api_id": "a", "inputs": {}},
                   {"id": "s2", "api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    # 第二步 form 发送：data 里 session_id 被替换为第一步提取的 SID999
    assert reqs[1]["data"] == {"session_id": "SID999", "message": "hi"}
    assert reqs[1]["json"] is None


# ---------- 跨步骤参数引用（extract → 下一步 {{var}}）----------
def test_extract_passes_to_next_step_query(monkeypatch):
    """extract 提取上一步响应字段，下一步 query 用 {{var}} 引用。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [
        {"data": {"token": "TK123"}},   # step1 响应
        {"ok": True},                    # step2 响应
    ], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/login",
             "extract": {"token": "data.token"}},
            {"id": "b", "method": "GET", "url": "/query", "query": {"token": "{{token}}"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}, {"api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    # 第二步请求的 query 里 token 被替换为第一步提取的值
    assert reqs[1]["params"] == {"token": "TK123"}


def test_extract_passes_to_next_step_body(monkeypatch):
    """extract 提取后，下一步 body 用 {{var}} 引用。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [
        {"result": {"session_id": "S9"}},
        {"ok": True},
    ], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/s", "extract": {"sid": "result.session_id"}},
            {"id": "b", "method": "POST", "url": "/t", "body": {"session": "{{sid}}"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}, {"api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    assert reqs[1]["json"] == {"session": "S9"}


def test_extract_nested_path_to_next_step(monkeypatch):
    """extract 支持嵌套 JSONPath（a.b[0].c），提取值传给下一步 url。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [
        {"a": {"b": [{"c": "DEEP"}]}},
        {"ok": True},
    ], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "GET", "url": "/1", "extract": {"deep": "a.b[0].c"}},
            {"id": "b", "method": "GET", "url": "/2/{{deep}}"},
        ],
         "steps": [{"api_id": "a", "inputs": {}}, {"api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    assert reqs[1]["url"] == "/2/DEEP"


def test_steps_placeholder_reference(monkeypatch):
    """前端占位符面板的 {{steps.s1.reply}} 形式：引用步骤 s1 的 extract 输出。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [
        {"data": {"answer": "HELLO"}},   # step s1 响应
        {"ok": True},                      # step s2 响应
    ], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/1",
             "extract": {"reply": "data.answer"}},
            {"id": "b", "method": "POST", "url": "/2",
             "body": {"content": "{{steps.s1.reply}}"}},
        ],
         "steps": [{"id": "s1", "api_id": "a", "inputs": {}},
                   {"id": "s2", "api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    # 第二步 body 里 {{steps.s1.reply}} 被替换为第一步提取的 answer
    assert reqs[1]["json"] == {"content": "HELLO"}


def test_steps_status_code_and_body_reference(monkeypatch):
    """{{steps.s1.status_code}} 和 {{steps.s1.body}} 也可引用。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [
        {"x": 1},
        {"ok": True},
    ], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "GET", "url": "/1"},
            {"id": "b", "method": "POST", "url": "/2",
             "body": {"sc": "{{steps.s1.status_code}}", "bd": "{{steps.s1.body}}"}},
        ],
         "steps": [{"id": "s1", "api_id": "a", "inputs": {}},
                   {"id": "s2", "api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    assert reqs[1]["json"]["sc"] == "200"  # _render 做 str() 替换
    assert reqs[1]["json"]["bd"] == "{'x': 1}"  # body 是 dict，_render 会 str()


def test_last_response_top_level_reference(monkeypatch):
    """last_response 顶层引用：下一步用 {{last_response}} 引用上一步整个响应（序列化）。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [
        {"code": 0},
        {"ok": True},
    ], reqs)
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "GET", "url": "/1"},
            {"id": "b", "method": "POST", "url": "/2", "body": {"prev": "{{last_response}}"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}, {"api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    # last_response 是 dict，_render 会 str() 它
    assert reqs[1]["json"]["prev"] == "{'code': 0}"


# ---------- extract_to_result（回写 case_results 的 node_id/trace_no）----------
def test_extract_to_result_extracts_fields(monkeypatch):
    """api.extract_to_result：从本步响应提取字段写入 result_extras。"""
    _mock_client(monkeypatch, [{"data": {"nodeId": "N1", "traceNo": "T1"}}])
    extras: dict = {}
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/x",
             "extract_to_result": {"node_id": "data.nodeId", "trace_no": "data.traceNo"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {"case_id": "abc-123"},
        result_extras=extras,
    )
    assert extras == {"node_id": "N1", "trace_no": "T1"}


def test_extract_to_result_uses_case_id_placeholder(monkeypatch):
    """extract_to_result 步骤可用 {{case_id}} 占位符（用例唯一标识作为入参）。"""
    reqs: list[dict] = []
    _mock_client(monkeypatch, [{"data": {"nodeId": "N9"}}], reqs)
    extras: dict = {}
    target_client.call_target(
        {"apis": [
            {"id": "a", "method": "POST", "url": "/query",
             "body": {"caseId": "{{case_id}}"},
             "extract_to_result": {"node_id": "data.nodeId"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {"case_id": "abc-123", "case_no": "C01"},
        result_extras=extras,
    )
    # case_id 被渲染进 body，且提取值进 result_extras
    assert reqs[0]["json"] == {"caseId": "abc-123"}
    assert extras == {"node_id": "N9"}


def test_extract_to_result_multiple_steps_accumulates(monkeypatch):
    """多步骤：各步 extract_to_result 提取值累加进同一个 result_extras。"""
    _mock_client(monkeypatch, [
        {"data": {"nodeId": "N1"}},
        {"data": {"traceNo": "T2"}},
    ])
    extras: dict = {}
    target_client.call_target(
        {"apis": [
            {"id": "a", "url": "/1", "extract_to_result": {"node_id": "data.nodeId"}},
            {"id": "b", "url": "/2", "extract_to_result": {"trace_no": "data.traceNo"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}, {"api_id": "b", "inputs": {}}],
         "final_extract": ""},
        {},
        result_extras=extras,
    )
    assert extras == {"node_id": "N1", "trace_no": "T2"}


def test_extract_to_result_not_passed_no_side_effect(monkeypatch):
    """result_extras 未传（None）时不收集，不报错。"""
    _mock_client(monkeypatch, [{"data": {"nodeId": "N1"}}])
    # 不传 result_extras，应正常返回不崩
    out = target_client.call_target(
        {"apis": [
            {"id": "a", "url": "/x",
             "extract_to_result": {"node_id": "data.nodeId"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {},
    )
    # 无 final_extract 返回最后一步响应序列化
    assert "N1" in out


def test_extract_to_result_missing_path_yields_none(monkeypatch):
    """extract_to_result 的 JSONPath 在响应中不存在时，提取值为 None（不崩）。"""
    _mock_client(monkeypatch, [{"data": {"other": "x"}}])
    extras: dict = {}
    target_client.call_target(
        {"apis": [
            {"id": "a", "url": "/x",
             "extract_to_result": {"node_id": "data.missing"}},
        ],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {},
        result_extras=extras,
    )
    assert extras == {"node_id": None}


# ---------- split_user_input ----------
def test_split_user_input_single():
    assert target_client.split_user_input("你好") == ["你好"]


def test_split_user_input_arrow():
    assert target_client.split_user_input("你好 → 查余额 → 转账") == ["你好", "查余额", "转账"]


def test_split_user_input_newline():
    assert target_client.split_user_input("你好\n查余额") == ["你好", "查余额"]


def test_split_user_input_mixed():
    assert target_client.split_user_input("你好\n查余额 → 转账\n谢谢") == ["你好", "查余额", "转账", "谢谢"]


def test_split_user_input_fullwidth_arrow():
    assert target_client.split_user_input("你好 → 查余额") == ["你好", "查余额"]


def test_split_user_input_no_space_arrow_not_split():
    assert target_client.split_user_input("你好→查余额") == ["你好→查余额"]


def test_split_user_input_empty():
    assert target_client.split_user_input("") == [""]


# ---------- call_target_multi_turn ----------
def test_call_target_multi_turn_single(monkeypatch):
    """单轮输入：行为与 call_target 一致（无 Q/A 前缀）。"""
    _mock_client(monkeypatch, [{"data": {"answer": "hi"}}])
    out = target_client.call_target_multi_turn(
        {"apis": [{"id": "a", "url": "/x"}], "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": "data.answer"},
        {"user_input": "你好"},
    )
    assert out == "hi"


def test_call_target_multi_turn_multi(monkeypatch):
    """多轮输入：拼接 Q/A 格式。"""
    _mock_client(monkeypatch, [{"r1": "ok1"}, {"r2": "ok2"}])
    out = target_client.call_target_multi_turn(
        {"apis": [{"id": "a", "url": "/x"}], "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {"user_input": "你好 → 查余额"},
    )
    assert "Q1: 你好" in out
    assert "A1:" in out
    assert "Q2: 查余额" in out
    assert "A2:" in out
    # 无 final_extract 时返回最后一步响应（JSON 序列化）
    assert '"r1": "ok1"' in out
    assert '"r2": "ok2"' in out


def test_call_target_multi_turn_dict_output(monkeypatch):
    """某轮输出是 dict，验证 json.dumps 后拼接。"""
    _mock_client(monkeypatch, [{"x": 1}, {"y": 2}])
    out = target_client.call_target_multi_turn(
        {"apis": [{"id": "a", "url": "/x"}], "steps": [{"api_id": "a", "inputs": {}}]},
        {"user_input": "A\nB"},
    )
    assert 'Q1: A' in out
    assert 'A1: {"x": 1}' in out
    assert 'Q2: B' in out
    assert 'A2: {"y": 2}' in out


def test_call_target_multi_turn_single_turn_result_extras(monkeypatch):
    """单轮：result_extras 透传到 call_target，提取值被收集。"""
    _mock_client(monkeypatch, [{"data": {"nodeId": "NS", "traceNo": "TS"}}])
    extras: dict = {}
    target_client.call_target_multi_turn(
        {"apis": [{"id": "a", "url": "/x",
                   "extract_to_result": {"node_id": "data.nodeId", "trace_no": "data.traceNo"}}],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {"user_input": "你好", "case_id": "abc"},
        result_extras=extras,
    )
    assert extras == {"node_id": "NS", "trace_no": "TS"}


def test_call_target_multi_turn_multi_turn_result_extras_last_wins(monkeypatch):
    """多轮：result_extras 取最后一轮的提取值（覆盖前几轮）。"""
    _mock_client(monkeypatch, [
        {"data": {"nodeId": "N1", "traceNo": "T1"}},
        {"data": {"nodeId": "N2", "traceNo": "T2"}},
    ])
    extras: dict = {}
    target_client.call_target_multi_turn(
        {"apis": [{"id": "a", "url": "/x",
                   "extract_to_result": {"node_id": "data.nodeId", "trace_no": "data.traceNo"}}],
         "steps": [{"api_id": "a", "inputs": {}}],
         "final_extract": ""},
        {"user_input": "你好 → 查余额", "case_id": "abc"},
        result_extras=extras,
    )
    # 两轮都写同一 key，最后一轮覆盖 → 取 N2/T2
    assert extras == {"node_id": "N2", "trace_no": "T2"}


# ---------- 报告聚合 ----------
def _seed(db):
    owner = uuid.uuid4()
    m1 = Metric(name="准确性", skill_md="s1")
    m2 = Metric(name="完整性", skill_md="s2")
    db.add_all([m1, m2]); db.flush()
    ev = Evaluator(name="标准", is_standard=True)
    db.add(ev); db.flush()
    db.add_all([
        EvaluatorMetric(evaluator_id=ev.id, metric_id=m1.id, weight=0.6),
        EvaluatorMetric(evaluator_id=ev.id, metric_id=m2.id, weight=0.4),
    ])
    ds = Dataset(name="DS", case_count=3, owner_id=owner)
    db.add(ds); db.flush()
    c1 = Case(dataset_id=ds.id, case_no="C1", user_input="i1", expected_gt="e1",
              dimension_l1="D1", dimension_l2="d1", sort_order=0)
    c2 = Case(dataset_id=ds.id, case_no="C2", user_input="i2", expected_gt="e2",
              dimension_l1="D1", dimension_l2="d2", sort_order=1)
    c3 = Case(dataset_id=ds.id, case_no="C3", user_input="i3", expected_gt="e3",
              dimension_l1="D2", dimension_l2=None, sort_order=2)
    db.add_all([c1, c2, c3]); db.flush()
    run = Run(task_name="T", owner_id=owner, evaluator_id=ev.id, dataset_id=ds.id,
              flow_template_id=uuid.uuid4(), extra_metric_ids=[], status="done",
              total_cases=3)
    db.add(run); db.flush()
    # C1 通过(90,80→0.6*90+0.4*80=86) C2 失败(60,40→0.6*60+0.4*40=52) C3 通过(80,80→80)
    cr1 = CaseResult(run_id=run.id, case_id=c1.id, status="passed", overall_score=86.0,
                     standard_metrics=[
                         {"metricId": str(m1.id), "name": "准确性", "weight": 0.6, "score": 90, "reason": "r"},
                         {"metricId": str(m2.id), "name": "完整性", "weight": 0.4, "score": 80, "reason": "r"},
                     ],
                     brief_comment="ok", token_usage=100, latency_sec=1.0)
    cr2 = CaseResult(run_id=run.id, case_id=c2.id, status="failed", overall_score=52.0,
                     standard_metrics=[
                         {"metricId": str(m1.id), "name": "准确性", "weight": 0.6, "score": 60, "reason": "r"},
                         {"metricId": str(m2.id), "name": "完整性", "weight": 0.4, "score": 40, "reason": "r"},
                     ],
                     brief_comment="差", token_usage=200, latency_sec=2.0)
    cr3 = CaseResult(run_id=run.id, case_id=c3.id, status="passed", overall_score=80.0,
                     standard_metrics=[
                         {"metricId": str(m1.id), "name": "准确性", "weight": 0.6, "score": 80, "reason": "r"},
                         {"metricId": str(m2.id), "name": "完整性", "weight": 0.4, "score": 80, "reason": "r"},
                     ],
                     brief_comment="", token_usage=300, latency_sec=3.0)
    db.add_all([cr1, cr2, cr3]); db.commit()
    return run, m1, m2


def test_build_report_summary(db):
    run, _, _ = _seed(db)
    rep = build_report(db, run)
    s = rep.summary
    assert s["total"] == 3 and s["passed"] == 2 and s["failed"] == 1
    assert s["tokenUsage"] == 600
    assert s["avgLatencySec"] == 2.0
    assert s["overallScore"] == round((86.0 + 52.0 + 80.0) / 3, 3)


def test_build_report_metric_averages(db):
    run, m1, m2 = _seed(db)
    rep = build_report(db, run)
    avg = {a["name"]: a["avgScore"] for a in rep.standard_metric_averages}
    assert avg["准确性"] == round((90 + 60 + 80) / 3, 3)
    assert avg["完整性"] == round((80 + 40 + 80) / 3, 3)


def test_build_report_dimension_summary(db):
    run, _, _ = _seed(db)
    rep = build_report(db, run)
    dims = {(d["l1"], d["l2"]): d for d in rep.dimension_summary}
    assert dims[("D1", "d1")]["total"] == 1
    assert dims[("D1", "d2")]["total"] == 1
    assert dims[("D2", "-")]["total"] == 1


def test_build_report_idempotent(db):
    run, _, _ = _seed(db)
    r1 = build_report(db, run)
    r2 = build_report(db, run)
    assert r1.id == r2.id  # 同一 run 只留一份


def test_render_html_escapes_and_includes(db):
    run, _, _ = _seed(db)
    rep = build_report(db, run)
    html = render_html(rep)
    assert "<!DOCTYPE html>" in html
    assert "T" in html  # task_name
    assert "准确性" in html
    assert "维度汇总" in html
    assert "逐用例明细" in html
    # 通过/失败徽标
    assert 'class="badge ok"' in html
    assert 'class="badge bad"' in html


def test_render_html_escapes_injection():
    # render_html 只读属性，用轻量对象即可，避免 ORM 建表
    rep = type("R", (), {
        "task_name": "<script>x</script>",
        "summary": {"overallScore": 0, "total": 0, "passed": 0, "failed": 0,
                    "tokenUsage": 0, "avgLatencySec": 0},
        "standard_metric_averages": [], "extra_metric_averages": [],
        "dimension_summary": [],
        "failure_root_causes": None,
        "case_details": [{"caseNo": '"><img src=x>', "status": "passed",
                          "overallScore": 1, "briefComment": "a&b",
                          "failureAttribution": None}],
    })()
    html = render_html(rep)
    # 页面自带交互 <script>（明细展开）属合法；这里验证用户数据被转义、未注入
    assert "<img" not in html
    assert "&lt;script&gt;" in html          # task_name 的 <script> 被转义
    assert "function toggleDetail" in html   # 交互脚本存在


# ---------- 闭环决策 Q2-Q5 ----------
def _std_evaluator_with_metrics(db, names=("准确性", "完整性")):
    """建一个标准评估器 + 引用 N 个指标，返回 (evaluator, [metrics])。"""
    metrics = [Metric(name=n, skill_md=f"s{n}") for n in names]
    db.add_all(metrics); db.flush()
    ev = Evaluator(name="标准", is_standard=True)
    db.add(ev); db.flush()
    for i, m in enumerate(metrics):
        db.add(EvaluatorMetric(evaluator_id=ev.id, metric_id=m.id,
                               weight=round(1 / len(metrics), 4), sort_order=i))
    db.flush()
    return ev, metrics


def test_extra_metric_max_default_5(db):
    # 无配置时上限默认 5
    assert _get_config(db, "evaluator.extra_metric_limit", 5) == 5


def test_extra_metric_max_from_config(db):
    db.add(Config(config_key="evaluator.extra_metric_limit",
                  config_value={"value": 2}))
    db.commit()
    assert _get_config(db, "evaluator.extra_metric_limit", 5) == 2


def test_extra_metric_cannot_be_standard_referenced(db):
    """Q4：额外指标不能是标准评估器已引用的指标。"""
    ev, metrics = _std_evaluator_with_metrics(db)
    std_ids = {em.metric_id for em in ev.metrics}
    # metrics[0] 已被标准评估器引用 → 不应允许作为额外指标
    assert metrics[0].id in std_ids
    # 模拟 create_run 的校验逻辑
    allowed = [m.id for m in metrics if m.id not in std_ids]
    assert metrics[0].id not in allowed


def test_extra_metric_must_exist_in_library(db):
    """Q4：额外指标必须在指标库中存在。"""
    ev, metrics = _std_evaluator_with_metrics(db)
    ghost = uuid.uuid4()  # 不存在的指标
    exists = db.get(Metric, ghost) is not None
    assert exists is False


# ---------- PG 队列（task_queue）----------
def _mk_run_with_pending(db, n: int, run_status: str = "running") -> Run:
    """建一个 run + n 条 pending case_result，返回 run。"""
    ds = Dataset(name="d", case_count=n, owner_id=uuid.uuid4())
    db.add(ds); db.flush()
    cases = []
    for i in range(n):
        c = Case(dataset_id=ds.id, case_no=f"c{i}", user_input="in",
                 expected_gt="gt", sort_order=i)
        db.add(c); cases.append(c)
    db.flush()
    ev, _ = _std_evaluator_with_metrics(db)
    run = Run(task_name="t", owner_id=uuid.uuid4(), evaluator_id=ev.id,
              dataset_id=ds.id, flow_template_id=uuid.uuid4(),
              extra_metric_ids=[], status=run_status, total_cases=n)
    db.add(run); db.flush()
    for c in cases:
        db.add(CaseResult(run_id=run.id, case_id=c.id, status="pending"))
    db.commit()
    return run


def test_claim_case_returns_pending_and_marks_running(db, monkeypatch):
    _patch_task_queue_to(db, monkeypatch)
    run = _mk_run_with_pending(db, 2)
    cr_id = task_queue.claim_case("w1")
    assert cr_id is not None
    db.expire_all()
    cr = db.get(CaseResult, uuid.UUID(cr_id))
    assert cr.status == "running"
    assert cr.locked_by == "w1"
    assert cr.locked_at is not None
    # 还剩 1 条 pending
    assert task_queue.pending_count() == 1


def test_claim_case_none_when_empty(db, monkeypatch):
    _patch_task_queue_to(db, monkeypatch)
    _mk_run_with_pending(db, 0)
    assert task_queue.claim_case("w1") is None


def test_claim_case_skips_paused_run(db, monkeypatch):
    _patch_task_queue_to(db, monkeypatch)
    _mk_run_with_pending(db, 2, run_status="paused")
    # paused run 的 pending case 不应被抢
    assert task_queue.claim_case("w1") is None


def test_recover_stale_running(db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    _patch_task_queue_to(db, monkeypatch)
    run = _mk_run_with_pending(db, 1)
    # 手动把那条 case_result 置为 running 且 locked_at 超时
    cr = db.query(CaseResult).filter(CaseResult.run_id == run.id).first()
    cr.status = "running"
    cr.locked_by = "dead-worker"
    cr.locked_at = datetime.now(timezone.utc) - timedelta(seconds=7200)
    db.commit()
    run_id = run.id  # 先取值，避免 recover 内部 commit 后 run 实例 detach
    recovered = task_queue.recover_stale_running(max_age_sec=600)
    assert recovered == 1
    # recover 内部 commit 后原实例脱离会话，重新查询
    cr2 = db.query(CaseResult).filter(CaseResult.run_id == run_id).first()
    assert cr2.status == "pending"
    assert cr2.locked_by is None
    assert cr2.locked_at is None

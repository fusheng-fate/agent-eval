"""前置 API 端到端验证：起本地 HTTP 服务，验证 form/json 两种 body_type。

验证链路：
  1. call_pre_api form 模式 → 被测系统收到 urlencoded 表单 → 返回 session
  2. call_pre_api json 模式 → 被测系统收到 JSON body → 返回 session
  3. ensure_session 缓存 + 过期刷新
  4. call_target 用 session 调后续 API（验证 {{session_id}} 占位符渲染）
"""
import json
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

import pytest

from app.modules.runs.target_client import (
    call_pre_api,
    call_target,
    ensure_case_session,
    ensure_session,
    get_group_variables,
)


# ---------- 本地 HTTP 服务（模拟被测系统） ----------

class MockTargetHandler(BaseHTTPRequestHandler):
    """模拟被测系统：/login 返回 session，/chat 验证 session。"""

    # 类变量：记录收到的请求
    received: list[dict] = []

    def log_message(self, *a):
        pass  # 静默

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def do_POST(self):
        body_raw = self._read_body()
        content_type = self.headers.get("Content-Type", "")

        record = {
            "path": self.path,
            "content_type": content_type,
            "body_raw": body_raw.decode("utf-8", errors="replace"),
        }

        if self.path == "/login":
            # 解析 body（form 或 json）
            if "application/x-www-form-urlencoded" in content_type:
                params = parse_qs(body_raw.decode())
                record["parsed"] = {k: v[0] for k, v in params.items()}
            else:
                record["parsed"] = json.loads(body_raw) if body_raw else {}

            MockTargetHandler.received.append(record)

            # 返回 session
            phone = record["parsed"].get("phone", "unknown")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "code": 0,
                "data": {"sessionId": f"sess-{phone}", "token": f"tok-{phone}"},
            }).encode())

        elif self.path == "/chat":
            # 验证 session
            record["parsed"] = json.loads(body_raw) if body_raw else {}
            MockTargetHandler.received.append(record)

            session_id = record["parsed"].get("session_id", "")
            reply = f"echo:{session_id}:{record['parsed'].get('message', '')}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": {"reply": reply}}).encode())

        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def mock_server():
    """起一个本地 HTTP 服务，返回 base_url。"""
    server = HTTPServer(("127.0.0.1", 0), MockTargetHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture(autouse=True)
def _reset_received():
    MockTargetHandler.received = []
    yield


# ---------- FakeRedis（独立于 conftest，因为本测试不依赖 db fixture） ----------

class FakeRedis:
    def __init__(self):
        self._store = {}
        self._ttl = {}

    def get(self, key):
        return self._store.get(key)

    def setex(self, key, ttl, value):
        self._store[key] = value
        self._ttl[key] = ttl

    def ttl(self, key):
        if key not in self._store:
            return -2
        return self._ttl.get(key, -1)

    def set(self, key, value, ex=None):
        self._store[key] = value
        if ex:
            self._ttl[key] = ex


# ---------- 测试 ----------

class TestPreApiForm:
    """前置 API form 模式。"""

    def test_form_login(self, mock_server):
        """form 模式：被测系统收到 urlencoded 表单，返回 session。"""
        pre_api = {
        "enabled": True,
            "method": "POST",
            "url": f"{mock_server}/login",
            "body_type": "form",
            "body": {"phone": "{{phone}}", "password": "{{password}}"},
            "extract": {"session_id": "data.sessionId", "token": "data.token"},
            "ttl_seconds": 3600,
        }
        variables = {"phone": "13800000001", "password": "pass1"}

        output = call_pre_api(pre_api, variables=variables)
        assert output["code"] == 0
        assert output["data"]["sessionId"] == "sess-13800000001"

        # 验证被测系统收到的请求
        req = MockTargetHandler.received[0]
        assert req["path"] == "/login"
        assert "application/x-www-form-urlencoded" in req["content_type"]
        # form 解析后 phone/password 正确
        assert req["parsed"]["phone"] == "13800000001"
        assert req["parsed"]["password"] == "pass1"

    def test_ensure_session_form(self, mock_server):
        """ensure_session + form 模式：缓存命中/过期刷新。"""
        r = FakeRedis()
        pre_api = {
        "enabled": True,
            "method": "POST",
            "url": f"{mock_server}/login",
            "body_type": "form",
            "body": {"phone": "{{phone}}", "password": "{{password}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        chain_json = {
            "pre_api": pre_api,
            "pre_api_groups": [{"phone": "111", "password": "p1"}],
            "variables": {},
        }
        rid = str(uuid.uuid4())

        # 第一次：缓存不存在 → 调前置 API
        v1 = ensure_session(rid, 0, chain_json, r)
        assert v1["session_id"] == "sess-111"
        assert v1["phone"] == "111"
        assert len(MockTargetHandler.received) == 1

        # 第二次：缓存命中（TTL=3600 > 60）→ 不调前置 API
        v2 = ensure_session(rid, 0, chain_json, r)
        assert v2["session_id"] == "sess-111"
        assert len(MockTargetHandler.received) == 1  # 没增加

        # 模拟快过期（TTL=30 < 60）→ 刷新
        cache_key = f"agent_eval:session:{rid}:0"
        r._ttl[cache_key] = 30
        v3 = ensure_session(rid, 0, chain_json, r)
        assert v3["session_id"] == "sess-111"  # 变量组不变
        assert len(MockTargetHandler.received) == 2  # 多调了 1 次


class TestPreApiJson:
    """前置 API json 模式。"""

    def test_json_login(self, mock_server):
        """json 模式：被测系统收到 JSON body，返回 session。"""
        pre_api = {
        "enabled": True,
            "method": "POST",
            "url": f"{mock_server}/login",
            "body_type": "json",
            "body": {"phone": "{{phone}}", "password": "{{password}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        variables = {"phone": "13800000002", "password": "pass2"}

        output = call_pre_api(pre_api, variables=variables)
        assert output["data"]["sessionId"] == "sess-13800000002"

        # 验证被测系统收到的请求
        req = MockTargetHandler.received[0]
        assert req["path"] == "/login"
        assert "application/json" in req["content_type"]
        assert req["parsed"]["phone"] == "13800000002"
        assert req["parsed"]["password"] == "pass2"


class TestFullChain:
    """完整链路：前置 API 拿 session → 后续 API 用 session 调接口。"""

    def test_form_session_to_chat(self, mock_server):
        """form 前置 API → session → chat API 验证 session 正确传递。"""
        pre_api = {
        "enabled": True,
            "method": "POST",
            "url": f"{mock_server}/login",
            "body_type": "form",
            "body": {"phone": "{{phone}}", "password": "{{password}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        chain_json = {
            "pre_api": pre_api,
            "pre_api_groups": [{"phone": "13800000001", "password": "pass1"}],
            "variables": {},
            "apis": [
                {
                    "id": "chat",
                    "method": "POST",
                    "url": f"{mock_server}/chat",
                    "body": {
                        "session_id": "{{session_id}}",
                        "message": "{{user_input}}",
                    },
                },
            ],
            "steps": [{"id": "s1", "api_id": "chat", "inputs": {}}],
            "final_extract": "data.reply",
        }
        r = FakeRedis()
        rid = str(uuid.uuid4())

        # 1. 获取 session
        group_vars = ensure_session(rid, 0, chain_json, r)
        assert group_vars["session_id"] == "sess-13800000001"
        assert group_vars["phone"] == "13800000001"

        # 2. 用 session 调 chat API
        row = {
            "case_id": "c1", "case_no": "C001",
            "user_input": "你好",
            **group_vars,  # session_id, phone 注入
        }
        result = call_target(chain_json, row)
        assert result == "echo:sess-13800000001:你好"

        # 3. 验证被测系统收到的 chat 请求带了正确的 session
        chat_req = MockTargetHandler.received[-1]
        assert chat_req["path"] == "/chat"
        assert chat_req["parsed"]["session_id"] == "sess-13800000001"
        assert chat_req["parsed"]["message"] == "你好"

    def test_json_session_to_chat(self, mock_server):
        """json 前置 API → session → chat API。"""
        pre_api = {
        "enabled": True,
            "method": "POST",
            "url": f"{mock_server}/login",
            "body_type": "json",
            "body": {"phone": "{{phone}}", "password": "{{password}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        chain_json = {
            "pre_api": pre_api,
            "pre_api_groups": [{"phone": "13800000002", "password": "pass2"}],
            "variables": {},
            "apis": [
                {
                    "id": "chat",
                    "method": "POST",
                    "url": f"{mock_server}/chat",
                    "body": {
                        "session_id": "{{session_id}}",
                        "message": "{{user_input}}",
                    },
                },
            ],
            "steps": [{"id": "s1", "api_id": "chat", "inputs": {}}],
            "final_extract": "data.reply",
        }
        r = FakeRedis()
        rid = str(uuid.uuid4())

        group_vars = ensure_session(rid, 0, chain_json, r)
        assert group_vars["session_id"] == "sess-13800000002"

        row = {
            "case_id": "c1", "case_no": "C001",
            "user_input": "hello",
            **group_vars,
        }
        result = call_target(chain_json, row)
        assert result == "echo:sess-13800000002:hello"

    def test_global_scope_no_rounds(self, mock_server):
        """无轮次模式（scope_key=global）：所有 case 共享一个 session。"""
        pre_api = {
        "enabled": True,
            "method": "POST",
            "url": f"{mock_server}/login",
            "body_type": "form",
            "body": {"phone": "{{phone}}", "password": "{{password}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        chain_json = {
            "pre_api": pre_api,
            "variables": {"phone": "13800000003", "password": "pass3"},
            "apis": [
                {
                    "id": "chat",
                    "method": "POST",
                    "url": f"{mock_server}/chat",
                    "body": {"session_id": "{{session_id}}", "message": "{{user_input}}"},
                },
            ],
            "steps": [{"id": "s1", "api_id": "chat", "inputs": {}}],
            "final_extract": "data.reply",
        }
        r = FakeRedis()
        rid = str(uuid.uuid4())

        # 3 个 case 共享同一个 session
        for i in range(3):
            group_vars = ensure_session(rid, "global", chain_json, r)
            assert group_vars["session_id"] == "sess-13800000003"

            row = {
                "case_id": f"c{i}", "case_no": f"C{i:03d}",
                "user_input": f"msg-{i}",
                **group_vars,
            }
            result = call_target(chain_json, row)
            assert result == f"echo:sess-13800000003:msg-{i}"

        # 前置 API 只调了 1 次（global session 共享）
        login_calls = [r for r in MockTargetHandler.received if r["path"] == "/login"]
        assert len(login_calls) == 1
        # chat 调了 3 次
        chat_calls = [r for r in MockTargetHandler.received if r["path"] == "/chat"]
        assert len(chat_calls) == 3

    def test_global_scope_with_groups(self, mock_server):
        """非轮次模式 + 变量组（v1.6）：按 sort_order 循环取组，每组独立 session。"""
        pre_api = {
        "enabled": True,
            "method": "POST",
            "url": f"{mock_server}/login",
            "body_type": "form",
            "body": {"phone": "{{phone}}", "password": "{{password}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        chain_json = {
            "pre_api": pre_api,
            "pre_api_groups": [
                {"phone": "13800000010", "password": "pa"},
                {"phone": "13800000011", "password": "pb"},
            ],
            "variables": {},
            "apis": [
                {
                    "id": "chat",
                    "method": "POST",
                    "url": f"{mock_server}/chat",
                    "body": {"session_id": "{{session_id}}", "message": "{{user_input}}"},
                },
            ],
            "steps": [{"id": "s1", "api_id": "chat", "inputs": {}}],
            "final_extract": "data.reply",
        }
        r = FakeRedis()
        rid = str(uuid.uuid4())

        # 4 个 case（sort_order 0..3）→ 组 0,1,0,1
        expected_sessions = [
            "sess-13800000010", "sess-13800000011",
            "sess-13800000010", "sess-13800000011",
        ]
        for i in range(4):
            group_vars = ensure_case_session(rid, i, chain_json, r)
            assert group_vars["session_id"] == expected_sessions[i]

            row = {
                "case_id": f"c{i}", "case_no": f"C{i:03d}",
                "user_input": f"msg-{i}",
                **group_vars,
            }
            result = call_target(chain_json, row)
            assert result == f"echo:{expected_sessions[i]}:msg-{i}"

        # 每组登录 1 次（组 0、组 1 各一次）
        login_calls = [rec for rec in MockTargetHandler.received if rec["path"] == "/login"]
        assert len(login_calls) == 2
        assert {rec["parsed"]["phone"] for rec in login_calls} == {"13800000010", "13800000011"}
        # chat 调了 4 次，session 与组对应
        chat_calls = [rec for rec in MockTargetHandler.received if rec["path"] == "/chat"]
        assert len(chat_calls) == 4
        assert [rec["parsed"]["session_id"] for rec in chat_calls] == expected_sessions

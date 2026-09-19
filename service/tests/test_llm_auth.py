"""LLM 认证（llm.auth）单元测试：静态/动态 token 解析、缓存提前量、401 自愈、写回 api_key。

不依赖真实 Redis / LLM：FakeRedis（conftest autouse）+ monkeypatch httpx.Client。
"""
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import redis_client
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models import Config, FlowTemplate, User
from app.modules.runs import llm_client
from app.modules.runs import routes as runs_routes

API_PREFIX = "/api"


def _resp(status, json=None, **kw):
    """构造带 request 的 httpx.Response（raise_for_status 需要 request 已设置）。"""
    r = httpx.Response(status, json=json, **kw)
    r.request = httpx.Request("POST", "http://fake")
    return r


def _admin(db):
    u = User(username="admin", password_hash=hash_password("p"), display_name="a", role="admin", is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _token_client(db):
    app = FastAPI()
    app.include_router(runs_routes.router, prefix=API_PREFIX)

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


# ---------- 静态 token ----------
def test_resolve_static_returns_bearer_api_key():
    cfg = {"api_key": "sk-abc", "auth": {"type": "static"}}
    token, q = llm_client.resolve_llm_token(None, cfg)
    assert token == "Bearer sk-abc"
    assert q == {}


def test_resolve_none_returns_empty():
    cfg = {"api_key": "sk-abc", "auth": {"type": "none"}}
    token, q = llm_client.resolve_llm_token(None, cfg)
    assert token == "" and q == {}


def test_call_llm_static_uses_bearer_header(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, params=None, json=None):
            captured["headers"] = headers
            captured["url"] = url
            return _resp(200, json={"choices": [{"message": {"content": '{"score": 80, "reason": "r", "brief_comment": "c"}'}}]},
            )

    monkeypatch.setattr(llm_client.httpx, "Client", _FakeClient)
    cfg = {"base_url": "http://x/v1", "api_key": "sk-abc", "model": "m",
           "auth": {"type": "static"}}
    token, q = llm_client.resolve_llm_token(None, cfg)
    cfg["_token"], cfg["_token_query"] = token, q
    llm_client.call_llm(cfg, "hi")
    assert captured["headers"]["Authorization"] == "Bearer sk-abc"


# ---------- 动态 token：缓存 + 提前量 + 写回 ----------
def _token_api(url="http://tok", extract="access_token", ttl=300, **extra):
    base = {"method": "POST", "url": url, "headers": {}, "query": {},
            "body": None, "extract": extract, "ttl": ttl, "timeout": 15}
    base.update(extra)
    return base


def test_resolve_dynamic_fetches_caches_and_writes_back(db, monkeypatch):
    db.add(Config(config_key="llm.api_key", config_value={"value": "old"},
                  scope="global", editable_by="admin", description="k"))
    db.commit()
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, headers=None, params=None, json=None, data=None):
            calls["n"] += 1
            return _resp(200, json={"access_token": "dyn-tok", "expires_in": 7200})

    monkeypatch.setattr(llm_client.httpx, "Client", _FakeClient)
    cfg = {"api_key": "old", "auth": {"type": "dynamic", "token_api": _token_api(ttl=300)}}

    token, q = llm_client.resolve_llm_token(db, cfg)
    assert token == "dyn-tok" and q == {}
    assert calls["n"] == 1
    # 写回 llm.api_key
    db.expire_all()
    assert db.query(Config).filter(Config.config_key == "llm.api_key").first().config_value == {"value": "dyn-tok"}
    # 缓存 TTL = ttl - 提前量(60)
    r = redis_client.get_redis()
    key = f"agent_eval:llm_token:{llm_client._auth_fingerprint(cfg['auth'])}"
    assert r.ttl(key) == 300 - llm_client.REFRESH_AHEAD_SEC
    # 第二次命中缓存，不再调接口
    token2, _ = llm_client.resolve_llm_token(db, cfg)
    assert token2 == "dyn-tok" and calls["n"] == 1


def test_resolve_dynamic_missing_url_raises():
    cfg = {"api_key": "x", "auth": {"type": "dynamic", "token_api": _token_api(url="")}}
    try:
        llm_client.resolve_llm_token(None, cfg)
        assert False, "应抛异常"
    except RuntimeError as e:
        assert "url" in str(e)


def test_resolve_dynamic_extract_not_found_raises(db, monkeypatch):
    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            return _resp(200, json={"data": {"token": "t"}})

    monkeypatch.setattr(llm_client.httpx, "Client", _FakeClient)
    cfg = {"api_key": "x", "auth": {"type": "dynamic", "token_api": _token_api(extract="access_token")}}
    try:
        llm_client.resolve_llm_token(db, cfg)
        assert False, "应抛异常"
    except RuntimeError as e:
        assert "解析失败" in str(e)


def test_invalidate_cache_forces_refetch(db, monkeypatch):
    db.add(Config(config_key="llm.api_key", config_value={"value": "old"},
                  scope="global", editable_by="admin", description="k"))
    db.commit()
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            calls["n"] += 1
            return _resp(200, json={"access_token": f"tok{calls['n']}"})

    monkeypatch.setattr(llm_client.httpx, "Client", _FakeClient)
    cfg = {"api_key": "old", "auth": {"type": "dynamic", "token_api": _token_api(ttl=300)}}
    llm_client.resolve_llm_token(db, cfg)
    assert calls["n"] == 1
    llm_client.invalidate_llm_token_cache(cfg["auth"])
    llm_client.resolve_llm_token(db, cfg)
    assert calls["n"] == 2  # 清缓存后强制重取


# ---------- 401 自愈 ----------
def test_call_llm_401_self_heal_dynamic(monkeypatch, db):
    db.add(Config(config_key="llm.api_key", config_value={"value": "stale"},
                  scope="global", editable_by="admin", description="k"))
    db.commit()
    seq = {"i": 0}

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, params=None, json=None):
            seq["i"] += 1
            if seq["i"] == 1:
                return _resp(401, json={"error": "expired"})
            return _resp(200, json={"choices": [{"message": {"content": '{"score": 80, "reason": "r", "brief_comment": "c"}'}}]},
            )

        def request(self, *a, **k):
            # token 接口
            return _resp(200, json={"access_token": "fresh"})

    monkeypatch.setattr(llm_client.httpx, "Client", _FakeClient)
    cfg = {"base_url": "http://x/v1", "api_key": "stale", "model": "m",
           "auth": {"type": "dynamic", "token_api": _token_api(extract="access_token", ttl=300)}}
    token, q = llm_client.resolve_llm_token(db, cfg)  # 先取一次（缓存）
    cfg["_token"], cfg["_token_query"], cfg["_db"] = token, q, db
    out = llm_client.call_llm(cfg, "hi")
    assert out["score"] == 80
    # 第二次 post 用了重取后的 fresh token
    assert "fresh" in (cfg["_token"] or "")


# ---------- flow_template.target_concurrency（v1.8 模板绑定） ----------
def test_flow_template_target_concurrency_default(db):
    t = FlowTemplate(name="t", chain_json={"apis": [], "steps": []})
    db.add(t)
    db.flush()  # 列默认值在 INSERT 时生效
    assert t.target_concurrency == 3


def test_flow_template_target_concurrency_set():
    t = FlowTemplate(name="t", chain_json={}, target_concurrency=8)
    assert t.target_concurrency == 8


# ---------- 手动刷新 token 接口（POST /runs/selfcheck/llm-token） ----------
def test_selfcheck_llm_token_static_rejected(db):
    u = _admin(db)
    db.add(Config(config_key="llm.auth", config_value={"value": {"type": "static"}},
                  scope="global", editable_by="admin", description="a"))
    db.commit()
    client = _token_client(db)
    headers = {"Authorization": f"Bearer {create_access_token(str(u.id), u.username, u.role)[0]}"}
    r = client.post(f"{API_PREFIX}/runs/selfcheck/llm-token", headers=headers)
    assert r.status_code == 422
    body = r.json()
    assert "非动态认证" in (body.get("message") or body.get("detail") or "")


def test_selfcheck_llm_token_dynamic_success(db, monkeypatch):
    u = _admin(db)
    db.add(Config(config_key="llm.auth", config_value={"value": {"type": "dynamic", "token_api": _token_api(ttl=300)}},
                  scope="global", editable_by="admin", description="a"))
    db.add(Config(config_key="llm.api_key", config_value={"value": "old"},
                  scope="global", editable_by="admin", description="k"))
    db.commit()

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            return _resp(200, json={"access_token": "manual-tok-12345"})

    monkeypatch.setattr(llm_client.httpx, "Client", _FakeClient)
    client = _token_client(db)
    headers = {"Authorization": f"Bearer {create_access_token(str(u.id), u.username, u.role)[0]}"}
    r = client.post(f"{API_PREFIX}/runs/selfcheck/llm-token", headers=headers)
    assert r.status_code == 200
    body = r.json()["data"]
    print("DEBUG body:", body)
    assert "manual-tok" in body["token_preview"]
    assert body["cache_ttl"] == 300 - llm_client.REFRESH_AHEAD_SEC
    # 写回 api_key
    db.expire_all()
    assert db.query(Config).filter(Config.config_key == "llm.api_key").first().config_value == {"value": "manual-tok-12345"}

"""configs 模块接口测试：列表 / 详情 / 更新（按 editable_by 权限，P16/P21）。

端到端验证 3 个接口的权限与包裹式响应（成功 {code:0,data}，异常走全局中间件）。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models import Config, User, UserConfig
from app.modules.configs import routes as configs_routes

API_PREFIX = "/api"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(configs_routes.router, prefix=API_PREFIX)
    return app


def _client(db) -> TestClient:
    app = _make_app()

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _user(db, username="alice", role="tester") -> User:
    u = User(username=username, password_hash=hash_password("pass123"), display_name=username, role=role, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _headers(user: User) -> dict:
    token, _ = create_access_token(str(user.id), user.username, user.role)
    return {"Authorization": f"Bearer {token}"}


def _config(db, key="llm.model", value=None, scope="global", editable_by="user", description=None) -> Config:
    c = Config(
        config_key=key,
        config_value=value if value is not None else {"value": "default-model"},
        scope=scope, editable_by=editable_by, description=description,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------- 列表（GET /configs） ----------
def test_list_configs_wrapped(db):
    u = _user(db)
    _config(db, key="llm.model")
    _config(db, key="pass.threshold", value={"value": 4}, editable_by="admin")
    r = _client(db).get(f"{API_PREFIX}/configs", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    data = body["data"]
    assert isinstance(data, list)
    assert len(data) == 2
    # 按 config_key 排序
    assert [c["config_key"] for c in data] == ["llm.model", "pass.threshold"]
    assert data[0]["config_value"] == {"value": "default-model"}
    assert data[1]["editable_by"] == "admin"


def test_list_configs_personal_override_visible(db):
    u = _user(db)
    _config(db, key="llm.model", value={"value": "global-model"}, scope="personal")
    db.add(UserConfig(user_id=u.id, config_key="llm.model", config_value={"value": "my-model"}))
    db.commit()
    r = _client(db).get(f"{API_PREFIX}/configs", headers=_headers(u))
    data = r.json()["data"]
    item = next(c for c in data if c["config_key"] == "llm.model")
    # 个人覆盖优先
    assert item["config_value"] == {"value": "my-model"}


# ---------- 详情（GET /configs/{key}） ----------
def test_get_config_wrapped(db):
    u = _user(db)
    _config(db, key="llm.model", value={"value": "m1"}, description="模型名")
    r = _client(db).get(f"{API_PREFIX}/configs/llm.model", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["config_key"] == "llm.model"
    assert body["data"]["config_value"] == {"value": "m1"}
    assert body["data"]["description"] == "模型名"


def test_get_config_missing_404(db):
    u = _user(db)
    r = _client(db).get(f"{API_PREFIX}/configs/no.such.key", headers=_headers(u))
    assert r.status_code == 404


# ---------- 批量更新（POST /configs/batch-update） ----------
def test_batch_update_admin_values(db):
    """admin 用 values 批量改全局；不存在的 key 跳过。"""
    admin = _user(db, username="admin", role="admin")
    _config(db, key="llm.model", value={"value": "old"})
    _config(db, key="pass.threshold", value={"value": 4}, editable_by="admin")
    r = _client(db).post(
        f"{API_PREFIX}/configs/batch-update",
        json={"values": {"llm.model": {"value": "new"}, "pass.threshold": 5, "ghost.key": 1}},
        headers=_headers(admin),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert sorted(data["updated"]) == ["llm.model", "pass.threshold"]
    assert data["skipped"] == ["ghost.key"]
    db.expire_all()
    assert db.query(Config).filter(Config.config_key == "llm.model").first().config_value == {"value": "new"}
    # 非 dict 值 5 被包成 {"value": 5}
    assert db.query(Config).filter(Config.config_key == "pass.threshold").first().config_value == {"value": 5}


def test_batch_update_user_only_personal(db):
    """普通用户批量：只处理个人级（scope=personal）。

    - 个人级 key（llm.model）→ 写 user_configs 覆盖。
    - 不存在的 key → 跳过（skipped）。
    - 全局非个人级 key → 403（无权改全局，与单 key 更新一致）。
    """
    u = _user(db)
    _config(db, key="llm.model", value={"value": "global"}, scope="personal")  # 个人级可改
    r = _client(db).post(
        f"{API_PREFIX}/configs/batch-update",
        json={"values": {"llm.model": {"value": "my"}, "ghost.key": 1}},
        headers=_headers(u),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["updated"] == ["llm.model"]
    assert data["skipped"] == ["ghost.key"]
    db.expire_all()
    # 个人级写入 user_configs
    uc = db.query(UserConfig).filter(UserConfig.user_id == u.id, UserConfig.config_key == "llm.model").first()
    assert uc is not None and uc.config_value == {"value": "my"}
    # 全局值未被普通用户改动
    assert db.query(Config).filter(Config.config_key == "llm.model").first().config_value == {"value": "global"}


def test_batch_update_user_forbidden_on_non_personal(db):
    """普通用户传非个人级、非 USER_EDITABLE 的 key → 403。"""
    u = _user(db)
    _config(db, key="target.endpoint", value={"value": "x"}, scope="global", editable_by="admin")
    r = _client(db).post(
        f"{API_PREFIX}/configs/batch-update",
        json={"values": {"target.endpoint": "y"}},
        headers=_headers(u),
    )
    assert r.status_code == 403


def test_batch_update_empty_422(db):
    admin = _user(db, username="admin", role="admin")
    r = _client(db).post(f"{API_PREFIX}/configs/batch-update", json={"values": {}}, headers=_headers(admin))
    assert r.status_code == 422
    # 缺 values 字段 → Pydantic 校验 422
    r2 = _client(db).post(f"{API_PREFIX}/configs/batch-update", json={}, headers=_headers(admin))
    assert r2.status_code == 422

"""users 模块接口测试：管理员添加用户 / 列表 / 改密 / 停用。

用 TestClient 挂载 users 路由 + SQLite 会话（get_db 覆盖），
端到端验证 4 个接口的权限、鉴权与包裹式响应。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models import User
from app.modules.users import routes as users_routes

API_PREFIX = "/api"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(users_routes.router, prefix=API_PREFIX)
    return app


def _client(db) -> TestClient:
    app = _make_app()

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _admin_user(db, username="admin", role="admin") -> User:
    u = User(
        username=username,
        password_hash=hash_password("admin123"),
        display_name="管理员",
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _admin_headers(admin: User) -> dict:
    token, _ = create_access_token(str(admin.id), admin.username, admin.role)
    return {"Authorization": f"Bearer {token}"}


# ---------- 管理员添加用户（POST /users） ----------
def test_create_user_ok(db):
    admin = _admin_user(db)
    r = _client(db).post(
        f"{API_PREFIX}/users",
        json={"username": "bob", "password": "pass123", "display_name": "鲍勃"},
        headers=_admin_headers(admin),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["username"] == "bob"
    assert data["display_name"] == "鲍勃"
    # 管理员注册的用户 role 固定 tester
    assert data["role"] == "tester"
    assert data["is_active"] is True


def test_create_user_defaults_display_name(db):
    admin = _admin_user(db)
    r = _client(db).post(
        f"{API_PREFIX}/users",
        json={"username": "bob", "password": "pass123"},
        headers=_admin_headers(admin),
    )
    assert r.status_code == 201
    assert r.json()["data"]["display_name"] == "bob"


def test_create_user_duplicate_username(db):
    admin = _admin_user(db)
    c = _client(db)
    h = _admin_headers(admin)
    payload = {"username": "bob", "password": "pass123"}
    c.post(f"{API_PREFIX}/users", json=payload, headers=h)
    r = c.post(f"{API_PREFIX}/users", json=payload, headers=h)
    # 业务冲突：HTTP 200 + code=40902
    assert r.status_code == 200
    assert r.json()["code"] == 40902
    assert r.json()["data"] is None


def test_create_user_requires_admin(db):
    # 普通用户（tester）不可添加
    tester = _admin_user(db, username="tester", role="tester")
    r = _client(db).post(
        f"{API_PREFIX}/users",
        json={"username": "bob", "password": "pass123"},
        headers=_admin_headers(tester),
    )
    assert r.status_code == 403


def test_create_user_no_token_401(db):
    r = _client(db).post(
        f"{API_PREFIX}/users",
        json={"username": "bob", "password": "pass123"},
    )
    assert r.status_code == 401


# ---------- 列表（GET /users） ----------
def test_list_users_paginated_and_wrapped(db):
    admin = _admin_user(db)
    c = _client(db)
    h = _admin_headers(admin)
    r = c.get(f"{API_PREFIX}/users", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["total"] >= 1
    assert isinstance(data["items"], list)


def test_list_users_keyword_filter(db):
    admin = _admin_user(db)
    # 再建一个 tester 用户
    u = User(username="bob", password_hash=hash_password("x"), display_name="鲍勃", role="tester", is_active=True)
    db.add(u)
    db.commit()
    r = _client(db).get(f"{API_PREFIX}/users", params={"keyword": "bob"}, headers=_admin_headers(admin))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["username"] == "bob"


# ---------- 改密（PUT /users/{id}/password） ----------
def test_change_password_ok(db):
    admin = _admin_user(db)
    tester = User(username="bob", password_hash=hash_password("old"), display_name="鲍勃", role="tester", is_active=True)
    db.add(tester)
    db.commit()
    db.refresh(tester)
    r = _client(db).post(
        f"{API_PREFIX}/users/{tester.id}/password",
        json={"password": "newpass"},
        headers=_admin_headers(admin),
    )
    assert r.status_code == 200
    assert r.json()["code"] == 0


def test_change_password_missing_user_404(db):
    admin = _admin_user(db)
    r = _client(db).post(
        f"{API_PREFIX}/users/00000000-0000-0000-0000-000000000000/password",
        json={"password": "x"},
        headers=_admin_headers(admin),
    )
    assert r.status_code == 404


# ---------- 停用（POST /users/{id}/deactivate） ----------
def test_deactivate_ok(db):
    admin = _admin_user(db)
    tester = User(username="bob", password_hash=hash_password("x"), display_name="鲍勃", role="tester", is_active=True)
    db.add(tester)
    db.commit()
    db.refresh(tester)
    r = _client(db).post(f"{API_PREFIX}/users/{tester.id}/deactivate", headers=_admin_headers(admin))
    assert r.status_code == 200
    assert r.json()["code"] == 0
    db.expire_all()
    assert db.get(User, tester.id).is_active is False


def test_deactivate_self_forbidden(db):
    admin = _admin_user(db)
    r = _client(db).post(f"{API_PREFIX}/users/{admin.id}/deactivate", headers=_admin_headers(admin))
    assert r.status_code == 400

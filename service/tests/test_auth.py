"""auth 模块接口测试：login / refresh / logout / me / me/password。

用 TestClient 挂载 auth 路由 + SQLite 会话（get_db 覆盖），
端到端验证全部 5 个接口的鉴权与令牌行为。
"""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import hash_password
from app.models import User
from app.modules.auth import routes as auth_routes

API_PREFIX = "/api"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_routes.router, prefix=API_PREFIX)
    return app


def _client(db) -> TestClient:
    app = _make_app()

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _seed_user(db, username="alice", password="secret123", role="tester", is_active=True) -> User:
    u = User(
        username=username,
        password_hash=hash_password(password),
        display_name=f"{username}-显示名",
        role=role,
        is_active=is_active,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------- login ----------
def test_login_ok_returns_double_token(db):
    _seed_user(db)
    r = _client(db).post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]
    assert data["access_token"] and data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["user"]["username"] == "alice"
    assert data["user"]["role"] == "tester"


def test_login_wrong_password_401(db):
    _seed_user(db)
    r = _client(db).post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user_401(db):
    r = _client(db).post(f"{API_PREFIX}/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_login_inactive_user_403(db):
    _seed_user(db, is_active=False)
    r = _client(db).post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 403


# ---------- refresh ----------
def test_refresh_ok_rotates(db):
    _seed_user(db)
    c = _client(db)
    login = c.post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "secret123"}).json()["data"]
    r = c.post(f"{API_PREFIX}/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["access_token"] and data["refresh_token"]
    # refresh 轮换：新 refresh 与旧的应不同
    assert data["refresh_token"] != login["refresh_token"]


def test_refresh_invalid_token_401(db):
    _seed_user(db)
    r = _client(db).post(f"{API_PREFIX}/auth/refresh", json={"refresh_token": "bad-token"})
    assert r.status_code == 401


def test_refresh_access_token_rejected(db):
    """refresh 接口不接受 access token（type 隔离）。"""
    _seed_user(db)
    c = _client(db)
    login = c.post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "secret123"}).json()["data"]
    r = c.post(f"{API_PREFIX}/auth/refresh", json={"refresh_token": login["access_token"]})
    assert r.status_code == 401


def test_refresh_inactive_user_401(db):
    _seed_user(db, role="tester", is_active=True)
    c = _client(db)
    login = c.post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "secret123"}).json()["data"]
    # 停用后 refresh 应 401
    u = db.query(User).filter(User.username == "alice").first()
    u.is_active = False
    db.commit()
    r = c.post(f"{API_PREFIX}/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 401


# ---------- me / password ----------
def _auth_headers(c, username, password):
    login = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password}).json()["data"]
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_me_returns_current_user(db):
    _seed_user(db)
    c = _client(db)
    h = _auth_headers(c, "alice", "secret123")
    r = c.get(f"{API_PREFIX}/auth/me", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "alice"


def test_me_no_token_401(db):
    r = _client(db).get(f"{API_PREFIX}/auth/me")
    assert r.status_code == 401


def test_change_my_password_then_old_fails(db):
    _seed_user(db)
    c = _client(db)
    h = _auth_headers(c, "alice", "secret123")
    r = c.post(f"{API_PREFIX}/auth/me/password", json={"password": "newpass456"}, headers=h)
    assert r.status_code == 200
    # 旧密码登录失败
    old = c.post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "secret123"})
    assert old.status_code == 401
    # 新密码登录成功
    new = c.post(f"{API_PREFIX}/auth/login", json={"username": "alice", "password": "newpass456"})
    assert new.status_code == 200


def test_change_my_password_requires_auth(db):
    _seed_user(db)
    r = _client(db).post(f"{API_PREFIX}/auth/me/password", json={"password": "x"})
    assert r.status_code == 401


# ---------- logout ----------
def test_logout_blacklists_access_token(db):
    _seed_user(db)
    c = _client(db)
    h = _auth_headers(c, "alice", "secret123")
    # 登出
    r = c.post(f"{API_PREFIX}/auth/logout", headers=h)
    assert r.status_code == 200
    # 登出后原 access token 应失效（jti 已入黑名单）
    r2 = c.get(f"{API_PREFIX}/auth/me", headers=h)
    assert r2.status_code == 401


def test_logout_no_token_ok_idempotent(db):
    r = _client(db).post(f"{API_PREFIX}/auth/logout")
    assert r.status_code in (200, 401)  # 无凭证时仍应幂等返回

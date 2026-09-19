"""metrics 模块接口测试：列表 / 详情 / 新建 / 更新 / 删除。

端到端验证 5 个接口的权限与包裹式响应（成功 {code:0,data}，异常走全局中间件）。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models import Evaluator, EvaluatorMetric, Metric, User
from app.modules.metrics import routes as metrics_routes

API_PREFIX = "/api"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(metrics_routes.router, prefix=API_PREFIX)
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


def _metric(db, name="准确性", category="tech", industry=None) -> Metric:
    m = Metric(name=name, category=category, industry=industry, skill_md="评分要求", is_builtin=False)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


# ---------- 列表（GET /metrics） ----------
def test_list_metrics_wrapped(db):
    u = _user(db)
    _metric(db)
    r = _client(db).get(f"{API_PREFIX}/metrics", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["items"][0]["name"] == "准确性"


def test_list_metrics_filters(db):
    u = _user(db)
    _metric(db, name="准确性", category="tech")
    _metric(db, name="业务价值", category="biz")
    c = _client(db)
    h = _headers(u)
    # category 过滤
    r = c.get(f"{API_PREFIX}/metrics", params={"category": "biz"}, headers=h)
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["name"] == "业务价值"
    # keyword 过滤
    r2 = c.get(f"{API_PREFIX}/metrics", params={"keyword": "准确"}, headers=h)
    assert r2.json()["data"]["total"] == 1


# ---------- 详情 ----------
def test_get_metric_wrapped(db):
    u = _user(db)
    m = _metric(db, name="完整性")
    r = _client(db).get(f"{API_PREFIX}/metrics/{m.id}", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "完整性"


def test_get_metric_missing_404(db):
    u = _user(db)
    r = _client(db).get(f"{API_PREFIX}/metrics/00000000-0000-0000-0000-000000000000", headers=_headers(u))
    assert r.status_code == 404


# ---------- 新建（POST /metrics） ----------
def test_create_metric_ok(db):
    admin = _user(db, username="admin", role="admin")
    r = _client(db).post(
        f"{API_PREFIX}/metrics",
        json={"name": "新指标", "category": "tech", "skill_md": "评分要求"},
        headers=_headers(admin),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "新指标"


def test_create_metric_duplicate_409(db):
    admin = _user(db, username="admin", role="admin")
    _metric(db, name="准确性")
    r = _client(db).post(
        f"{API_PREFIX}/metrics",
        json={"name": "准确性", "skill_md": "x"},
        headers=_headers(admin),
    )
    assert r.status_code == 409


def test_create_metric_requires_admin(db):
    tester = _user(db, username="tester", role="tester")
    r = _client(db).post(
        f"{API_PREFIX}/metrics",
        json={"name": "新指标", "skill_md": "x"},
        headers=_headers(tester),
    )
    assert r.status_code == 403


# ---------- 更新（POST /metrics/{id}/update） ----------
def test_update_metric_ok(db):
    admin = _user(db, username="admin", role="admin")
    m = _metric(db, name="旧名")
    r = _client(db).post(
        f"{API_PREFIX}/metrics/{m.id}/update",
        json={"name": "新名", "description": "新描述"},
        headers=_headers(admin),
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "新名"


def test_update_metric_missing_404(db):
    admin = _user(db, username="admin", role="admin")
    r = _client(db).post(
        f"{API_PREFIX}/metrics/00000000-0000-0000-0000-000000000000/update",
        json={"name": "x"},
        headers=_headers(admin),
    )
    assert r.status_code == 404


# ---------- 删除（POST /metrics/{id}/delete） ----------
def test_delete_metric_ok(db):
    admin = _user(db, username="admin", role="admin")
    m = _metric(db)
    r = _client(db).post(f"{API_PREFIX}/metrics/{m.id}/delete", headers=_headers(admin))
    assert r.status_code == 200
    assert r.json()["code"] == 0
    db.expire_all()
    assert db.get(Metric, m.id) is None


def test_delete_metric_referenced_409(db):
    admin = _user(db, username="admin", role="admin")
    m = _metric(db)
    ev = Evaluator(name="标准", is_standard=True)
    db.add(ev); db.flush()
    db.add(EvaluatorMetric(evaluator_id=ev.id, metric_id=m.id, weight=1, sort_order=0))
    db.commit()
    r = _client(db).post(f"{API_PREFIX}/metrics/{m.id}/delete", headers=_headers(admin))
    assert r.status_code == 409


def test_delete_metric_requires_admin(db):
    tester = _user(db, username="tester", role="tester")
    m = _metric(db)
    r = _client(db).post(f"{API_PREFIX}/metrics/{m.id}/delete", headers=_headers(tester))
    assert r.status_code == 403

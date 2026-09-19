"""evaluators 模块接口测试：查看 / 更新标准评估器。

端到端验证 2 个接口的权限与包裹式响应（成功 {code:0,data}，异常走全局中间件）。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models import Evaluator, EvaluatorMetric, Metric, User
from app.modules.evaluators import routes as evaluators_routes

API_PREFIX = "/api"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(evaluators_routes.router, prefix=API_PREFIX)
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


def _standard_with_metrics(db) -> Evaluator:
    """建标准评估器 + 引用 2 个指标（权重和=1）。"""
    m1 = Metric(name="准确性", category="tech", skill_md="s1")
    m2 = Metric(name="完整性", category="tech", skill_md="s2")
    db.add_all([m1, m2]); db.flush()
    ev = Evaluator(name="标准", is_standard=True)
    db.add(ev); db.flush()
    db.add_all([
        EvaluatorMetric(evaluator_id=ev.id, metric_id=m1.id, weight=0.6, sort_order=0),
        EvaluatorMetric(evaluator_id=ev.id, metric_id=m2.id, weight=0.4, sort_order=1),
    ])
    db.commit()
    db.refresh(ev)
    return ev


# ---------- 查看（GET /evaluators/standard） ----------
def test_get_standard_wrapped(db):
    u = _user(db)
    _standard_with_metrics(db)
    r = _client(db).get(f"{API_PREFIX}/evaluators/standard", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["name"] == "标准"
    assert len(data["metrics"]) == 2
    # 按 sort_order 排序，weight 为 float
    assert data["metrics"][0]["name"] == "准确性"
    assert data["metrics"][0]["weight"] == 0.6


def test_get_standard_not_initialized_500(db):
    u = _user(db)
    r = _client(db).get(f"{API_PREFIX}/evaluators/standard", headers=_headers(u))
    assert r.status_code == 500


# ---------- 更新（POST /evaluators/standard/update） ----------
def test_update_standard_ok(db):
    admin = _user(db, username="admin", role="admin")
    ev = _standard_with_metrics(db)
    m1, m2 = ev.metrics[0].metric_id, ev.metrics[1].metric_id
    r = _client(db).post(
        f"{API_PREFIX}/evaluators/standard/update",
        json={
            "description": "新描述",
            "metrics": [
                {"metric_id": str(m1), "weight": 0.5, },
                {"metric_id": str(m2), "weight": 0.5, },
            ],
        },
        headers=_headers(admin),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["description"] == "新描述"
    assert all(m["weight"] == 0.5 for m in body["data"]["metrics"])


def test_update_standard_weight_sum_not_one_422(db):
    admin = _user(db, username="admin", role="admin")
    ev = _standard_with_metrics(db)
    m1, m2 = ev.metrics[0].metric_id, ev.metrics[1].metric_id
    r = _client(db).post(
        f"{API_PREFIX}/evaluators/standard/update",
        json={"metrics": [
            {"metric_id": str(m1), "weight": 0.5, },
            {"metric_id": str(m2), "weight": 0.3, },
        ]},
        headers=_headers(admin),
    )
    assert r.status_code == 422


def test_update_standard_metric_not_exist_422(db):
    admin = _user(db, username="admin", role="admin")
    ev = _standard_with_metrics(db)
    m1 = ev.metrics[0].metric_id
    r = _client(db).post(
        f"{API_PREFIX}/evaluators/standard/update",
        json={"metrics": [
            {"metric_id": str(m1), "weight": 0.5, },
            {"metric_id": "00000000-0000-0000-0000-000000000000", "weight": 0.5, },
        ]},
        headers=_headers(admin),
    )
    assert r.status_code == 422


def test_update_standard_requires_admin(db):
    tester = _user(db, username="tester", role="tester")
    ev = _standard_with_metrics(db)
    m1, m2 = ev.metrics[0].metric_id, ev.metrics[1].metric_id
    r = _client(db).post(
        f"{API_PREFIX}/evaluators/standard/update",
        json={"metrics": [
            {"metric_id": str(m1), "weight": 0.5, },
            {"metric_id": str(m2), "weight": 0.5, },
        ]},
        headers=_headers(tester),
    )
    assert r.status_code == 403

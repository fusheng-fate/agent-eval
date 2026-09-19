"""flow_templates 模块接口测试：列表 / 详情 / 新建 / 更新 / 删除 / 校验。

端到端验证 6 个接口的权限与包裹式响应（成功 {code:0,data}，异常走全局中间件）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models import FlowTemplate, Run, User
from app.modules.flow_templates import routes as flow_templates_routes

API_PREFIX = "/api"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(flow_templates_routes.router, prefix=API_PREFIX)
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


CHAIN = {"apis": [{"id": "a1", "method": "GET", "url": "http://x"}], "steps": [{"api_id": "a1"}]}


def _template(db, owner, name="模板A") -> FlowTemplate:
    t = FlowTemplate(name=name, description="d", chain_json=CHAIN, created_by=owner.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ---------- 列表（GET /flow-templates） ----------
def test_list_templates_wrapped(db):
    u = _user(db)
    _template(db, u)
    r = _client(db).get(f"{API_PREFIX}/flow-templates", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list)
    assert body["data"][0]["name"] == "模板A"


# ---------- 详情 ----------
def test_get_template_wrapped(db):
    u = _user(db)
    t = _template(db, u, name="T")
    r = _client(db).get(f"{API_PREFIX}/flow-templates/{t.id}", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "T"
    assert body["data"]["chain_json"]["apis"][0]["id"] == "a1"


def test_get_template_missing_404(db):
    u = _user(db)
    r = _client(db).get(f"{API_PREFIX}/flow-templates/00000000-0000-0000-0000-000000000000", headers=_headers(u))
    assert r.status_code == 404


# ---------- 新建（POST /flow-templates） ----------
def test_create_template_ok(db):
    admin = _user(db, username="admin", role="admin")
    c = _client(db)
    r = c.post(
        f"{API_PREFIX}/flow-templates",
        json={"name": "新模板", "description": "d", "chain_json": CHAIN, "param_perms": [{"paramPath": "apis[0].timeout", "userEditable": True}]},
        headers=_headers(admin),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "新模板"
    assert body["data"]["param_perms"] == [{"paramPath": "apis[0].timeout", "userEditable": True}]


def test_create_template_requires_admin(db):
    tester = _user(db, username="tester", role="tester")
    r = _client(db).post(
        f"{API_PREFIX}/flow-templates",
        json={"name": "新模板", "chain_json": CHAIN},
        headers=_headers(tester),
    )
    assert r.status_code == 403


# ---------- 更新（POST /flow-templates/{id}/update） ----------
def test_update_template_ok(db):
    admin = _user(db, username="admin", role="admin")
    t = _template(db, admin, name="旧名")
    r = _client(db).post(
        f"{API_PREFIX}/flow-templates/{t.id}/update",
        json={"name": "新名", "description": "d2", "chain_json": CHAIN, "param_perms": []},
        headers=_headers(admin),
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "新名"


def test_update_template_missing_404(db):
    admin = _user(db, username="admin", role="admin")
    r = _client(db).post(
        f"{API_PREFIX}/flow-templates/00000000-0000-0000-0000-000000000000/update",
        json={"name": "x", "chain_json": CHAIN},
        headers=_headers(admin),
    )
    assert r.status_code == 404


# ---------- 删除（POST /flow-templates/{id}/delete） ----------
def test_delete_template_ok(db):
    admin = _user(db, username="admin", role="admin")
    t = _template(db, admin)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/delete", headers=_headers(admin))
    assert r.status_code == 200
    assert r.json()["code"] == 0
    db.expire_all()
    assert db.get(FlowTemplate, t.id) is None


def _run_with_template(db, admin, t, status):
    from app.models import Dataset, Evaluator
    ev = Evaluator(name="e", is_standard=True)
    db.add(ev); db.flush()
    ds = Dataset(name="ds", owner_id=admin.id, case_count=0)
    db.add(ds); db.flush()
    run = Run(task_name="r", owner_id=admin.id, evaluator_id=ev.id, dataset_id=ds.id,
              flow_template_id=t.id, extra_metric_ids=[], status=status, total_cases=0)
    db.add(run); db.commit()
    return run


def test_delete_template_done_run_referenced_allowed(db):
    """终态（done）任务引用中的模板可删。"""
    admin = _user(db, username="admin", role="admin")
    t = _template(db, admin)
    _run_with_template(db, admin, t, "done")
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/delete", headers=_headers(admin))
    assert r.status_code == 200
    db.expire_all()
    assert db.get(FlowTemplate, t.id) is None


@pytest.mark.parametrize("status", ["pending", "running", "paused"])
def test_delete_template_active_run_referenced_blocked(db, status):
    """活跃态（等待/运行/暂停）任务引用中的模板禁止删除。"""
    admin = _user(db, username="admin", role="admin")
    t = _template(db, admin)
    _run_with_template(db, admin, t, status)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/delete", headers=_headers(admin))
    assert r.status_code == 409
    db.expire_all()
    assert db.get(FlowTemplate, t.id) is not None


def test_delete_template_requires_admin(db):
    tester = _user(db, username="tester", role="tester")
    t = _template(db, tester)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/delete", headers=_headers(tester))
    assert r.status_code == 403


# ---------- 校验（POST /flow-templates/{id}/validate） ----------
def test_validate_ok(db):
    u = _user(db)
    t = _template(db, u)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert "校验通过" in body["data"]["message"]


def test_validate_bad_step_ref_422(db):
    u = _user(db)
    bad_chain = {"apis": [{"id": "a1"}], "steps": [{"api_id": "ghost"}]}
    t = FlowTemplate(name="bad", chain_json=bad_chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422


# ---------- 校验 final_extract（v1.3） ----------
def test_validate_final_extract_string_ok(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1"}], "steps": [{"api_id": "a1"}], "final_extract": "data.x"}
    t = FlowTemplate(name="fe-str", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 200


def test_validate_final_extract_dict_ok(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1"}, {"id": "a2"}],
             "steps": [{"api_id": "a1"}, {"api_id": "a2"}],
             "final_extract": {"x": {"step": 0, "path": "a"}, "y": {"path": "b"}}}
    t = FlowTemplate(name="fe-dict", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 200


def test_validate_final_extract_dict_step_out_of_range_422(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1"}], "steps": [{"api_id": "a1"}],
             "final_extract": {"x": {"step": 5, "path": "a"}}}
    t = FlowTemplate(name="fe-bad-step", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422


def test_validate_final_extract_dict_empty_path_422(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1"}], "steps": [{"api_id": "a1"}],
             "final_extract": {"x": {"step": 0, "path": ""}}}
    t = FlowTemplate(name="fe-bad-path", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422


def test_validate_final_extract_dict_spec_not_dict_422(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1"}], "steps": [{"api_id": "a1"}],
             "final_extract": {"x": "a"}}  # spec 不是 {step, path} 对象
    t = FlowTemplate(name="fe-bad-spec", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422


def test_validate_final_extract_bad_type_422(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1"}], "steps": [{"api_id": "a1"}], "final_extract": 123}
    t = FlowTemplate(name="fe-bad-type", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422


# ---------- 校验 extract_to_result（回写 case_results 的 node_id/trace_no）----------
def test_validate_extract_to_result_ok(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1", "extract_to_result": {"node_id": "data.nodeId", "trace_no": "data.traceNo"}}],
             "steps": [{"api_id": "a1"}]}
    t = FlowTemplate(name="etr-ok", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 200


def test_validate_extract_to_result_not_dict_422(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1", "extract_to_result": "data.nodeId"}],
             "steps": [{"api_id": "a1"}]}
    t = FlowTemplate(name="etr-not-dict", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422


def test_validate_extract_to_result_empty_path_422(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1", "extract_to_result": {"node_id": ""}}],
             "steps": [{"api_id": "a1"}]}
    t = FlowTemplate(name="etr-empty-path", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422


def test_validate_extract_to_result_non_string_path_422(db):
    u = _user(db)
    chain = {"apis": [{"id": "a1", "extract_to_result": {"node_id": 123}}],
             "steps": [{"api_id": "a1"}]}
    t = FlowTemplate(name="etr-non-str", chain_json=chain, created_by=u.id)
    db.add(t); db.commit(); db.refresh(t)
    r = _client(db).post(f"{API_PREFIX}/flow-templates/{t.id}/validate", headers=_headers(u))
    assert r.status_code == 422

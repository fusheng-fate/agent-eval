"""datasets 模块接口测试：列表 / 详情 / 预览 / 用例 / 上传 / 删除。

端到端验证 6 个接口的权限与包裹式响应（成功 {code:0,data}，异常走全局中间件）。
"""
import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models import Case, Dataset, User
from app.modules.datasets import routes as datasets_routes

API_PREFIX = "/api"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(datasets_routes.router, prefix=API_PREFIX)
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


def _dataset(db, owner, name="DS", case_count=0) -> Dataset:
    d = Dataset(name=name, owner_id=owner.id, source="excel", case_count=case_count)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _xlsx_bytes(rows, header=("编号", "输入", "预期")):
    """构造一个 .xlsx 文件字节。rows 为数据行列表（每行 tuple）。"""
    wb = Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- 列表（GET /datasets） ----------
def test_list_datasets_wrapped(db):
    u = _user(db)
    _dataset(db, u, name="数据集A")
    r = _client(db).get(f"{API_PREFIX}/datasets", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["items"][0]["name"] == "数据集A"
    # 列表包含上传人 username
    assert data["items"][0]["username"] == "alice"


def test_list_datasets_includes_username(db):
    """列表项应带上传人 username（join users）。"""
    u = _user(db, username="alice")
    other = _user(db, username="bob")
    _dataset(db, u, name="A")
    _dataset(db, other, name="B")
    r = _client(db).get(f"{API_PREFIX}/datasets", headers=_headers(u))
    items = {i["name"]: i["username"] for i in r.json()["data"]["items"]}
    assert items == {"A": "alice", "B": "bob"}


def test_list_datasets_keyword_and_owner_mine(db):
    u = _user(db)
    other = _user(db, username="bob")
    _dataset(db, u, name="我的数据")
    _dataset(db, other, name="别人的数据")
    c = _client(db)
    # keyword 过滤
    r = c.get(f"{API_PREFIX}/datasets", params={"keyword": "我的"}, headers=_headers(u))
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["name"] == "我的数据"
    # owner=mine 只看自己
    r2 = c.get(f"{API_PREFIX}/datasets", params={"owner": "mine"}, headers=_headers(u))
    assert r2.json()["data"]["total"] == 1


def test_list_datasets_filter_by_username(db):
    """按归属人 username 精确过滤。"""
    u = _user(db, username="alice")
    other = _user(db, username="bob")
    _dataset(db, u, name="A的数据")
    _dataset(db, other, name="B的数据")
    c = _client(db)
    r = c.get(f"{API_PREFIX}/datasets", params={"username": "bob"}, headers=_headers(u))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["name"] == "B的数据"
    # 不存在的 username → 空
    r2 = c.get(f"{API_PREFIX}/datasets", params={"username": "ghost"}, headers=_headers(u))
    assert r2.json()["data"]["total"] == 0


def test_list_datasets_filter_by_created_range(db):
    """按创建时间区间（ISO 字符串）过滤。"""
    from datetime import datetime, timezone
    u = _user(db)
    d1 = _dataset(db, u, name="早的")
    d2 = _dataset(db, u, name="晚的")
    # 人为错开 created_at
    db.query(Dataset).filter(Dataset.id == d1.id).update({"created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)})
    db.query(Dataset).filter(Dataset.id == d2.id).update({"created_at": datetime(2026, 6, 1, tzinfo=timezone.utc)})
    db.commit()
    c = _client(db)
    # 只取 2026-03 ~ 2026-08 → 命中 d2
    r = c.get(f"{API_PREFIX}/datasets", params={"created_start": "2026-03-01T00:00:00", "created_end": "2026-08-01T00:00:00"}, headers=_headers(u))
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["name"] == "晚的"
    # 只给 start → 命中 >= start 的（d2）
    r2 = c.get(f"{API_PREFIX}/datasets", params={"created_start": "2026-05-01T00:00:00"}, headers=_headers(u))
    assert r2.json()["data"]["total"] == 1
    # 只给 end → 命中 <= end 的（d1）
    r3 = c.get(f"{API_PREFIX}/datasets", params={"created_end": "2026-02-01T00:00:00"}, headers=_headers(u))
    assert r3.json()["data"]["total"] == 1
    assert r3.json()["data"]["items"][0]["name"] == "早的"


def test_list_datasets_combined_filters(db):
    """username + 名称 + 时间区间组合过滤。"""
    from datetime import datetime, timezone
    u = _user(db, username="alice")
    other = _user(db, username="bob")
    d1 = _dataset(db, u, name="回归集")
    d2 = _dataset(db, other, name="回归集")
    d3 = _dataset(db, other, name="冒烟集")
    db.query(Dataset).filter(Dataset.id == d1.id).update({"created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)})
    db.query(Dataset).filter(Dataset.id == d2.id).update({"created_at": datetime(2026, 7, 1, tzinfo=timezone.utc)})
    db.query(Dataset).filter(Dataset.id == d3.id).update({"created_at": datetime(2026, 7, 1, tzinfo=timezone.utc)})
    db.commit()
    c = _client(db)
    # bob 的、名称含"回归"、2026 年内 → 仅 d2
    r = c.get(
        f"{API_PREFIX}/datasets",
        params={"username": "bob", "keyword": "回归", "created_start": "2026-01-01T00:00:00", "created_end": "2026-12-31T00:00:00"},
        headers=_headers(u),
    )
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["name"] == "回归集"
    assert data["items"][0]["owner_id"] == str(other.id)


# ---------- 详情 / 预览 / 用例 ----------
def test_get_dataset_wrapped(db):
    u = _user(db)
    d = _dataset(db, u, name="DS")
    r = _client(db).get(f"{API_PREFIX}/datasets/{d.id}", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "DS"


def test_get_dataset_missing_404(db):
    u = _user(db)
    r = _client(db).get(f"{API_PREFIX}/datasets/00000000-0000-0000-0000-000000000000", headers=_headers(u))
    assert r.status_code == 404


def test_preview_wrapped(db):
    u = _user(db)
    d = _dataset(db, u, name="DS")
    for i in range(3):
        db.add(Case(dataset_id=d.id, case_no=f"c{i}", user_input="in", expected_gt="gt", sort_order=i))
    db.commit()
    r = _client(db).get(f"{API_PREFIX}/datasets/{d.id}/preview", headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["headers"] == ["用例编号", "测试输入", "预期结果", "评测一级维度", "评测二级维度"]
    assert len(data["rows"]) == 3


def test_list_cases_paginated(db):
    u = _user(db)
    d = _dataset(db, u)
    for i in range(25):
        db.add(Case(dataset_id=d.id, case_no=f"c{i}", user_input="in", expected_gt="gt", sort_order=i))
    db.commit()
    r = _client(db).get(f"{API_PREFIX}/datasets/{d.id}/cases", params={"page": 2, "page_size": 10}, headers=_headers(u))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 25
    assert data["page"] == 2
    assert len(data["items"]) == 10


# ---------- 下载（GET /datasets/{id}/download） ----------
def test_download_dataset_excel(db):
    """导出 .xlsx：表头参照 column_mapping（标准字段→原表头），数据来自 cases。"""
    from openpyxl import load_workbook
    u = _user(db)
    d = _dataset(db, u, name="下载集")
    d.column_mapping = {"case_no": "编号", "user_input": "输入", "expected_gt": "预期", "dimension_l1": "一级", "dimension_l2": "二级"}
    for i in range(3):
        db.add(Case(dataset_id=d.id, case_no=f"c{i}", user_input=f"in{i}", expected_gt=f"gt{i}",
                    dimension_l1="L1", dimension_l2="L2", sort_order=i))
    db.commit()
    r = _client(db).get(f"{API_PREFIX}/datasets/{d.id}/download", headers=_headers(u))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert f"dataset_{d.id}.xlsx" in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content)).active
    rows = list(ws.iter_rows(values_only=True))
    # 表头用原表头名
    assert rows[0] == ("编号", "输入", "预期", "一级", "二级")
    # 数据行
    assert rows[1] == ("c0", "in0", "gt0", "L1", "L2")
    assert len(rows) == 4  # 表头 + 3 行


def test_download_dataset_no_mapping_fallback(db):
    """无 column_mapping 时表头回退为标准字段名。"""
    from openpyxl import load_workbook
    u = _user(db)
    d = _dataset(db, u, name="无映射")
    db.add(Case(dataset_id=d.id, case_no="c1", user_input="in", expected_gt="gt", sort_order=0))
    db.commit()
    r = _client(db).get(f"{API_PREFIX}/datasets/{d.id}/download", headers=_headers(u))
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("case_no", "user_input", "expected_gt", "dimension_l1", "dimension_l2")
    assert rows[1][:3] == ("c1", "in", "gt")
    assert rows[1][3] in (None, "") and rows[1][4] in (None, "")


def test_download_dataset_missing_404(db):
    u = _user(db)
    r = _client(db).get(f"{API_PREFIX}/datasets/00000000-0000-0000-0000-000000000000/download", headers=_headers(u))
    assert r.status_code == 404


# ---------- 上传（POST /datasets/upload） ----------
def test_upload_ok(db):
    u = _user(db)
    c = _client(db)
    mapping = json.dumps({"case_no": "编号", "user_input": "输入", "expected_gt": "预期", "dimension_l1": None, "dimension_l2": None})
    content = _xlsx_bytes([("C1", "输入1", "预期1"), ("C2", "输入2", "预期2")])
    r = c.post(
        f"{API_PREFIX}/datasets/upload",
        data={"name": "上传集", "column_mapping": mapping},
        files={"file": ("d.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=_headers(u),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "上传集"
    assert body["data"]["case_count"] == 2


def test_upload_missing_required_mapping_422(db):
    u = _user(db)
    c = _client(db)
    # 缺 expected_gt 映射
    mapping = json.dumps({"case_no": "编号", "user_input": "输入", "expected_gt": "", "dimension_l1": None, "dimension_l2": None})
    content = _xlsx_bytes([("C1", "输入1", "预期1")])
    r = c.post(
        f"{API_PREFIX}/datasets/upload",
        data={"name": "上传集", "column_mapping": mapping},
        files={"file": ("d.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=_headers(u),
    )
    assert r.status_code == 422


def test_upload_bad_extension_400(db):
    u = _user(db)
    c = _client(db)
    mapping = json.dumps({"case_no": "编号", "user_input": "输入", "expected_gt": "预期"})
    r = c.post(
        f"{API_PREFIX}/datasets/upload",
        data={"name": "上传集", "column_mapping": mapping},
        files={"file": ("d.csv", b"a,b,c", "text/csv")},
        headers=_headers(u),
    )
    assert r.status_code == 400


# ---------- 重命名（POST /datasets/{id}/rename） ----------
def test_rename_dataset_ok(db):
    u = _user(db)
    d = _dataset(db, u, name="旧名")
    r = _client(db).post(f"{API_PREFIX}/datasets/{d.id}/rename", json={"name": "新名"}, headers=_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "新名"
    db.expire_all()
    assert db.get(Dataset, d.id).name == "新名"


def test_rename_dataset_other_forbidden(db):
    u = _user(db)
    other = _user(db, username="bob")
    d = _dataset(db, other, name="别人的")
    r = _client(db).post(f"{API_PREFIX}/datasets/{d.id}/rename", json={"name": "改"}, headers=_headers(u))
    assert r.status_code == 403


def test_rename_dataset_admin_can_rename_any(db):
    admin = _user(db, username="admin", role="admin")
    other = _user(db, username="bob")
    d = _dataset(db, other, name="别人的")
    r = _client(db).post(f"{API_PREFIX}/datasets/{d.id}/rename", json={"name": "管理员改的"}, headers=_headers(admin))
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "管理员改的"


def test_rename_dataset_missing_404(db):
    u = _user(db)
    r = _client(db).post(f"{API_PREFIX}/datasets/00000000-0000-0000-0000-000000000000/rename", json={"name": "x"}, headers=_headers(u))
    assert r.status_code == 404


# ---------- 删除（POST /datasets/{id}/delete） ----------
def test_delete_own_dataset_ok(db):
    u = _user(db)
    d = _dataset(db, u)
    r = _client(db).post(f"{API_PREFIX}/datasets/{d.id}/delete", headers=_headers(u))
    assert r.status_code == 200
    assert r.json()["code"] == 0
    db.expire_all()
    assert db.get(Dataset, d.id) is None


def test_delete_other_dataset_forbidden(db):
    u = _user(db)
    other = _user(db, username="bob")
    d = _dataset(db, other)
    r = _client(db).post(f"{API_PREFIX}/datasets/{d.id}/delete", headers=_headers(u))
    assert r.status_code == 403


def test_delete_admin_can_delete_any(db):
    admin = _user(db, username="admin", role="admin")
    other = _user(db, username="bob")
    d = _dataset(db, other)
    r = _client(db).post(f"{API_PREFIX}/datasets/{d.id}/delete", headers=_headers(admin))
    assert r.status_code == 200


def test_delete_missing_404(db):
    u = _user(db)
    r = _client(db).post(f"{API_PREFIX}/datasets/00000000-0000-0000-0000-000000000000/delete", headers=_headers(u))
    assert r.status_code == 404


# ---------- 批量删除（POST /datasets/batch-delete，仅管理员） ----------
def test_batch_delete_ok(db):
    admin = _user(db, username="admin", role="admin")
    other = _user(db, username="bob")
    d1 = _dataset(db, other, name="A")
    d2 = _dataset(db, other, name="B")
    # 带 case 的数据集，验证级联删除
    db.add(Case(dataset_id=d1.id, case_no="c1", user_input="in", expected_gt="gt", sort_order=0))
    db.commit()
    r = _client(db).post(
        f"{API_PREFIX}/datasets/batch-delete",
        json={"ids": [str(d1.id), str(d2.id)]},
        headers=_headers(admin),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["deleted"] == 2
    db.expire_all()
    assert db.get(Dataset, d1.id) is None
    assert db.get(Dataset, d2.id) is None
    assert db.query(Case).filter(Case.dataset_id == d1.id).count() == 0


def test_batch_delete_empty_ids_422(db):
    admin = _user(db, username="admin", role="admin")
    r = _client(db).post(f"{API_PREFIX}/datasets/batch-delete", json={"ids": []}, headers=_headers(admin))
    assert r.status_code == 422


def test_batch_delete_missing_id_404(db):
    admin = _user(db, username="admin", role="admin")
    r = _client(db).post(
        f"{API_PREFIX}/datasets/batch-delete",
        json={"ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=_headers(admin),
    )
    assert r.status_code == 404


def test_batch_delete_invalid_id_422(db):
    admin = _user(db, username="admin", role="admin")
    r = _client(db).post(f"{API_PREFIX}/datasets/batch-delete", json={"ids": ["not-a-uuid"]}, headers=_headers(admin))
    assert r.status_code == 422


def test_batch_delete_requires_admin(db):
    u = _user(db, username="alice", role="tester")
    d = _dataset(db, u)
    r = _client(db).post(f"{API_PREFIX}/datasets/batch-delete", json={"ids": [str(d.id)]}, headers=_headers(u))
    assert r.status_code == 403

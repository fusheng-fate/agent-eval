"""评测结果打分（导入 Excel 直接打分）测试。

覆盖：
- import_eval_results 解析 Excel → 建 Dataset(source=eval_import) + Cases + Run(mode=eval_import) + CaseResult(pending, agent_output 已填)
- P25 单活跃任务约束
- worker.process_case 对 eval_import 任务跳过调被测 Agent（call_target_multi_turn 不被调用），
  直接读 case_results.agent_output 走 LLM 打分 → 加权 → 落库
"""
import asyncio
import io
import json
import uuid

from openpyxl import Workbook

from app.models import Case, CaseResult, Dataset, Evaluator, EvaluatorMetric, Metric, Run, User
from app.modules.runs import llm_client, task_queue, worker
from app.modules.runs.routes import import_eval_results


def _drain_scoring(db):
    """执行与评分解耦后，process_case 只执行（置 executed）。手动驱动评分到终态。"""
    for _ in range(10):
        cr_id = task_queue.claim_score_task("score-test")
        if cr_id is None:
            break
        worker.process_score(cr_id)
    db.expire_all()


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _std_evaluator(db, names=("准确性", "完整性")):
    metrics = [Metric(name=n, skill_md=f"s{n}") for n in names]
    db.add_all(metrics); db.flush()
    ev = Evaluator(name="标准", is_standard=True)
    db.add(ev); db.flush()
    for i, m in enumerate(metrics):
        db.add(EvaluatorMetric(evaluator_id=ev.id, metric_id=m.id,
                               weight=round(1 / len(metrics), 4), sort_order=i))
    db.flush()
    return ev, metrics


def _user(db, role="user") -> User:
    u = User(username=f"u{uuid.uuid4().hex[:8]}", password_hash="x",
             display_name="t", role=role, is_active=True)
    db.add(u); db.flush()
    return u


HEADER = ["用例编号", "测试输入", "预期结果", "执行结果", "评测一级维度", "评测二级维度"]
MAPPING = {
    "case_no": "用例编号", "user_input": "测试输入", "expected_gt": "预期结果",
    "agent_output": "执行结果", "dimension_l1": "评测一级维度", "dimension_l2": "评测二级维度",
}


def _fake_file(filename, data: bytes):
    """构造最小 UploadFile 桩：有 filename + 可 await 的 read(size=None)。"""
    async def _read(size=None):
        return data
    return type("F", (), {"filename": filename, "read": _read})()


def _call_import(db, user, rows, task_name="导入任务", extra="[]"):
    """调 async 路由，返回 RunOut（ok() 直接返回 Pydantic 对象，response_model 序列化在真实 HTTP 层）。"""
    data = _xlsx_bytes([HEADER] + rows)
    coro = import_eval_results(
        file=_fake_file("r.xlsx", data),
        task_name=task_name,
        column_mapping=json.dumps(MAPPING),
        extra_metric_ids=extra,
        db=db,
        user=user,
    )
    return asyncio.run(coro)


def test_import_creates_dataset_run_cases(db):
    _std_evaluator(db)
    user = _user(db)
    rows = [
        ["C1", "输入1", "预期1", "输出1", "D1", "d1"],
        ["C2", "输入2", "预期2", "输出2", "D1", "d2"],
        ["C3", "输入3", "预期3", "输出3", "D2", None],
    ]
    out = _call_import(db, user, rows)["data"]
    run_id = out.id
    assert out.mode == "eval_import"
    assert out.status == "running"
    assert out.total_cases == 3

    run = db.get(Run, uuid.UUID(run_id))
    assert run.mode == "eval_import"
    assert run.flow_template_id is None
    ds = db.get(Dataset, run.dataset_id)
    assert ds.source == "eval_import"
    assert ds.case_count == 3

    cases = db.query(Case).filter(Case.dataset_id == ds.id).all()
    assert len(cases) == 3
    # case_results：pending + agent_output 已填
    crs = db.query(CaseResult).filter(CaseResult.run_id == run.id).all()
    assert len(crs) == 3
    for cr in crs:
        assert cr.status == "pending"
        assert cr.agent_output  # 已填
    # agent_output 与 Excel 行对应
    by_case = {cr.case_id: cr for cr in crs}
    c1 = next(c for c in cases if c.case_no == "C1")
    assert by_case[c1.id].agent_output == "输出1"


def test_import_skips_rows_missing_required(db):
    _std_evaluator(db)
    user = _user(db)
    rows = [
        ["C1", "输入1", "预期1", "输出1", "D1", "d1"],
        ["C2", "", "预期2", "输出2", "D1", "d2"],  # 缺 user_input → 跳过
        ["C3", "输入3", "预期3", "", "D2", "d3"],   # 缺 agent_output → 跳过
    ]
    out = _call_import(db, user, rows)["data"]
    assert out.total_cases == 1


def test_import_p25_conflict_when_active_run(db):
    user = _user(db)
    # 先建一个 running 任务
    ev, _ = _std_evaluator(db)
    ds = Dataset(name="d", case_count=1, owner_id=user.id)
    db.add(ds); db.flush()
    c = Case(dataset_id=ds.id, case_no="c", user_input="i", expected_gt="e", sort_order=0)
    db.add(c); db.flush()
    run = Run(task_name="active", owner_id=user.id, evaluator_id=ev.id,
              dataset_id=ds.id, flow_template_id=uuid.uuid4(), mode="exec",
              extra_metric_ids=[], status="running", total_cases=1)
    db.add(run); db.commit()

    # 再导入 → 409
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        _call_import(db, user, [["C1", "i", "e", "o", None, None]])
    assert ei.value.status_code == 409


def test_import_rejects_non_xlsx(db):
    _std_evaluator(db)
    user = _user(db)
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        asyncio.run(import_eval_results(
            file=_fake_file("r.csv", b""),
            task_name="t", column_mapping=json.dumps(MAPPING), extra_metric_ids="[]",
            db=db, user=user,
        ))
    assert ei.value.status_code == 400


def _patch_worker_to(db, monkeypatch):
    """让 worker / task_queue 内部 SessionLocal 指向测试 SQLite。

    worker 用测试 db 实例本身（异常路径 rollback/commit 直接作用于测试 session，
    与原行为一致）；task_queue 用 sessionmaker 新 session（claim_score_task 会
    close 自身 session，避免关掉测试 db）。
    """
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    TestSession = sessionmaker(bind=db.bind, autoflush=False, autocommit=False)
    monkeypatch.setattr(task_queue, "SessionLocal", TestSession)


def _mock_llm(monkeypatch, scores: list[float]):
    """mock score_all_metrics，一次返回所有指标分数（不真调 LLM）。"""
    calls = {"n": 0}

    def fake_score_all(cfg, std_metrics, extra_metrics, row, agent_output):
        # scores 列表按指标顺序给出预设分数
        std_out = []
        for i, m in enumerate(std_metrics):
            sc = scores[i % len(scores)]
            std_out.append({"metric_id": m["id"], "score": sc, "reason": "r"})
        calls["n"] += 1
        return {
            "standard_metrics": std_out,
            "extra_metrics": [],
            "brief_comment": "c",
            "failure_attribution": None,
            "usage": {"total_tokens": 10}, "latency_sec": 0.5,
        }
    monkeypatch.setattr(worker, "score_all_metrics", fake_score_all)
    return calls


def test_process_case_eval_import_skips_target(db, monkeypatch):
    """eval_import 任务：不调被测 Agent，直接读 cr.agent_output 打分。"""
    _patch_worker_to(db, monkeypatch)
    ev, metrics = _std_evaluator(db)  # 2 个标准指标
    user = _user(db)
    ds = Dataset(name="d", case_count=1, owner_id=user.id, source="eval_import")
    db.add(ds); db.flush()
    c = Case(dataset_id=ds.id, case_no="C1", user_input="输入", expected_gt="预期",
             dimension_l1="D1", dimension_l2="d1", sort_order=0)
    db.add(c); db.flush()
    run = Run(task_name="imp", owner_id=user.id, evaluator_id=ev.id, dataset_id=ds.id,
              flow_template_id=None, mode="eval_import", extra_metric_ids=[],
              status="running", total_cases=1)
    db.add(run); db.flush()
    cr = CaseResult(run_id=run.id, case_id=c.id, status="running",
                    agent_output="被测输出XYZ")
    db.add(cr); db.commit()

    # 关键断言：call_target_multi_turn 不应被调用
    target_called = {"v": False}
    monkeypatch.setattr(worker, "call_target_multi_turn",
                        lambda *a, **k: target_called.__setitem__("v", True) or "SHOULD_NOT")
    # LLM 打分：准确性=90, 完整性=80 → 主分 0.5*90+0.5*80=85（默认阈值 80 → passed）
    _mock_llm(monkeypatch, [90, 80])

    worker.process_case(str(cr.id))
    _drain_scoring(db)

    assert target_called["v"] is False, "eval_import 不应调被测 Agent"
    # worker 内部 commit 后原 ORM 实例可能 detach，统一用 query 重查
    cr2 = db.query(CaseResult).filter(CaseResult.run_id == run.id).first()
    assert cr2.status == "passed"
    assert cr2.overall_score == 85.0
    assert cr2.agent_output == "被测输出XYZ"
    # run 收尾
    run2 = db.query(Run).filter(Run.id == run.id).first()
    assert run2.status == "done"
    assert run2.passed_cases == 1
    assert run2.overall_score == 85.0


def test_process_case_eval_import_failed_below_threshold(db, monkeypatch):
    """分数低于阈值 → failed。"""
    _patch_worker_to(db, monkeypatch)
    ev, metrics = _std_evaluator(db)
    user = _user(db)
    ds = Dataset(name="d", case_count=1, owner_id=user.id, source="eval_import")
    db.add(ds); db.flush()
    c = Case(dataset_id=ds.id, case_no="C1", user_input="输入", expected_gt="预期", sort_order=0)
    db.add(c); db.flush()
    run = Run(task_name="imp", owner_id=user.id, evaluator_id=ev.id, dataset_id=ds.id,
              flow_template_id=None, mode="eval_import", extra_metric_ids=[],
              status="running", total_cases=1)
    db.add(run); db.flush()
    cr = CaseResult(run_id=run.id, case_id=c.id, status="running", agent_output="输出")
    db.add(cr); db.commit()

    monkeypatch.setattr(worker, "call_target_multi_turn", lambda *a, **k: "SHOULD_NOT")
    _mock_llm(monkeypatch, [40, 60])  # 0.5*40+0.5*60=50 < 80 → failed

    worker.process_case(str(cr.id))
    _drain_scoring(db)

    cr2 = db.query(CaseResult).filter(CaseResult.run_id == run.id).first()
    assert cr2.status == "failed"
    assert cr2.overall_score == 50.0


def test_process_case_exec_missing_template_errors_clearly(db, monkeypatch):
    """exec 任务缺流程模板（flow_template_id=None）→ 明确报错，而非 template.chain_json 的 AttributeError。"""
    _patch_worker_to(db, monkeypatch)
    ev, _ = _std_evaluator(db)
    user = _user(db)
    ds = Dataset(name="d", case_count=1, owner_id=user.id)
    db.add(ds); db.flush()
    c = Case(dataset_id=ds.id, case_no="C1", user_input="i", expected_gt="e", sort_order=0)
    db.add(c); db.flush()
    # mode=exec（默认）但没模板——数据异常场景
    run = Run(task_name="bad", owner_id=user.id, evaluator_id=ev.id, dataset_id=ds.id,
              flow_template_id=None, mode="exec", extra_metric_ids=[],
              status="running", total_cases=1)
    db.add(run); db.flush()
    cr = CaseResult(run_id=run.id, case_id=c.id, status="running")
    db.add(cr); db.commit()
    run_id = run.id  # 异常路径 rollback 后实例会 detach，先取 id

    worker.process_case(str(cr.id))

    cr2 = db.query(CaseResult).filter(CaseResult.run_id == run_id).first()
    assert cr2.status == "error"
    assert "缺少流程模板" in (cr2.error_msg or "")

"""真实 PG/Redis 联调：建 Run + CaseResult → 手动跑 worker.process_case → 断言 run_logs 落库。

不依赖 LLM / 被测 Agent：monkeypatch worker 内的 _score 与 call_target_multi_turn。
运行：.venv/Scripts/python -m pytest tests/test_run_logs_live.py -v
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models import Case, CaseResult, Dataset, Evaluator, FlowTemplate, Metric, Run, RunLog, User
from app.modules.runs import task_queue, worker


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _admin_token(client: TestClient) -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def test_run_logs_written_by_worker(client: TestClient, monkeypatch):
    headers = {"Authorization": f"Bearer {_admin_token(client)}"}
    db = SessionLocal()
    try:
        # 找 admin 用户
        user = db.query(User).filter(User.username == "admin").first()
        assert user is not None

        # 建一个最小流程模板（exec 任务必需）
        tpl = FlowTemplate(name=f"log-test-{uuid.uuid4().hex[:6]}", chain_json={
            "vars": {}, "apis": [{"id": "a1", "method": "POST", "url": "http://127.0.0.1:9/x", "body": {}}],
            "steps": [{"id": "s1", "api_id": "a1", "inputs": {}}], "final_extract": "data",
        })
        db.add(tpl)
        db.flush()

        # 建数据集 + 用例
        ds = Dataset(name=f"log-ds-{uuid.uuid4().hex[:6]}", owner_id=user.id, source="test")
        db.add(ds)
        db.flush()
        case = Case(dataset_id=ds.id, case_no="L01", user_input="hi", expected_gt="ok", sort_order=1)
        db.add(case)
        db.flush()
        ds.case_count = 1

        # 标准评估器（bootstrap 已建）+ 挂一个指标
        evaluator = db.query(Evaluator).filter(Evaluator.is_standard.is_(True)).first()
        assert evaluator is not None
        metric = db.query(Metric).first()
        if metric is None:
            metric = Metric(name="log-metric", skill_md="给 0-100 分，输出 JSON {score, reason}")
            db.add(metric)
            db.flush()
        from app.models import EvaluatorMetric
        if not any(em.metric_id == metric.id for em in evaluator.metrics):
            db.add(EvaluatorMetric(evaluator_id=evaluator.id, metric_id=metric.id, weight=1.0))
            db.flush()

        # 建 Run + CaseResult
        run = Run(
            task_name=f"log-run-{uuid.uuid4().hex[:6]}", owner_id=user.id,
            evaluator_id=evaluator.id, dataset_id=ds.id, flow_template_id=tpl.id,
            mode="exec", status="running", total_cases=1, extra_metric_ids=[],
        )
        db.add(run)
        db.flush()
        cr = CaseResult(run_id=run.id, case_id=case.id, status="pending")
        db.add(cr)
        db.commit()
        run_id, cr_id = run.id, cr.id

        # mock 掉外部调用
        monkeypatch.setattr(worker, "call_target_multi_turn", lambda *a, **k: "MOCK_OUTPUT")
        monkeypatch.setattr(worker, "score_metric", lambda *a, **k: {
            "score": 95, "reason": "mock", "failure_attribution": None,
        })

        # 手动跑 worker 执行该 case（执行与评分解耦：process_case 只执行，置 executed）
        worker.process_case(str(cr_id))
        # 手动驱动评分池：抢 executed → 评分到终态
        score_id = task_queue.claim_score_task("score-test")
        assert score_id is not None
        worker.process_score(score_id)

        # 断言：run_logs 有记录
        logs = db.query(RunLog).filter(RunLog.run_id == run_id).order_by(RunLog.created_at.asc()).all()
        assert len(logs) >= 3, f"期望至少 3 条日志，实际 {len(logs)}: {[l.message for l in logs]}"
        assert any("开始执行用例" in l.message for l in logs)
        assert any("被测 Agent 执行完成" in l.message for l in logs)
        assert any("评分完成" in l.message for l in logs)
        assert any("通过" in l.message or "未通过" in l.message for l in logs)

        # 断言：接口能查到
        r = client.get(f"/api/runs/{run_id}/logs", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert len(data) >= 3
        assert data[0]["level"] in ("info", "success", "warn", "error")

        # 断言：run 状态流转完成
        db.refresh(run)
        assert run.status == "done", f"run.status={run.status}"
        assert run.done_cases == run.total_cases == 1
    finally:
        db.close()

"""轮次执行全链路测试（SQLite 内存 + FakeRedis）。

覆盖：
- 创建任务时 round_size 切分（10 用例 / round_size=3 → 4 轮，最后一轮 1 个）
- claim_round 抢整组（组内所有 case 置 running）
- process_round 组内串行执行 + 变量组循环分配
- ensure_session 缓存命中 / 过期刷新
- 完成检测（done_rounds >= total_rounds → run done）
- 非轮次模式（round_size=None）走原有 claim_case 路径

注意：claim_round / claim_case / process_round 内部用 SessionLocal() 创建新 session，
测试需 monkeypatch task_queue.SessionLocal 和 worker.SessionLocal 指向测试 engine。
"""
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.core.database import SessionLocal
from app.models import Case, CaseResult, Dataset, Evaluator, EvaluatorMetric, FlowTemplate, Metric, Run, User
from app.modules.runs import task_queue, worker
from app.modules.runs.target_client import ensure_session, get_group_variables


@pytest.fixture(autouse=True)
def _patch_sessionlocal(db, monkeypatch):
    """让 task_queue / worker 内部的 SessionLocal() 指向测试 engine。"""
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=db.bind, autoflush=False, autocommit=False)
    monkeypatch.setattr(task_queue, "SessionLocal", TestSession)
    monkeypatch.setattr(worker, "SessionLocal", TestSession)
    yield


# ---------- 辅助 ----------

def _utcnow():
    return datetime.now(timezone.utc)


def _drain_scoring(w, task_queue, db, max_rounds: int = 50) -> None:
    """同步跑完所有待评分 case（executed → passed/failed）。

    执行与评分解耦后，process_round/process_case 只执行不评分。
    测试需手动驱动评分池：循环 claim_score_task + process_score 直到无 executed。
    """
    for _ in range(max_rounds):
        cr_id = task_queue.claim_score_task("score-test")
        if cr_id is None:
            break
        w.process_score(cr_id)
    db.expire_all()


def _std_evaluator(db, names=("准确性",)):
    metrics = [Metric(name=n, skill_md=f"s{n}") for n in names]
    db.add_all(metrics)
    db.flush()
    ev = Evaluator(name="标准", is_standard=True)
    db.add(ev)
    db.flush()
    for i, m in enumerate(metrics):
        db.add(EvaluatorMetric(evaluator_id=ev.id, metric_id=m.id,
                               weight=round(1 / len(metrics), 4), sort_order=i))
    db.flush()
    return ev, metrics


def _user(db, role="user") -> User:
    u = User(username=f"u{uuid.uuid4().hex[:8]}", password_hash="x",
             display_name="t", role=role, is_active=True)
    db.add(u)
    db.flush()
    return u


def _dataset_with_cases(db, owner_id, case_count, round_size=None):
    """建数据集 + N 个用例（sort_order 1..N），可选设置 round_no。"""
    ds = Dataset(name=f"ds-{uuid.uuid4().hex[:6]}", owner_id=owner_id, source="test")
    db.add(ds)
    db.flush()
    for i in range(1, case_count + 1):
        c = Case(
            dataset_id=ds.id, case_no=f"C{i:03d}", user_input=f"input-{i}",
            expected_gt="ok", sort_order=i,
        )
        if round_size:
            c.round_no = (i - 1) // round_size
        db.add(c)
    db.flush()
    ds.case_count = case_count
    db.flush()
    return ds


def _chain_json(pre_api_groups=None, pre_api=None, variables=None):
    """构造最小 chain_json。"""
    cj = {
        "apis": [{"id": "a1", "method": "POST", "url": "http://mock/agent", "body": {}}],
        "steps": [{"id": "s1", "api_id": "a1", "inputs": {}}],
        "variables": variables or {},
        "final_extract": "data",
    }
    if pre_api:
        cj["pre_api"] = pre_api
    if pre_api_groups:
        cj["pre_api_groups"] = pre_api_groups
    return cj


def _run(db, owner_id, evaluator_id, dataset_id, template_id, round_size=None,
         total_cases=0, total_rounds=None, status="running"):
    run = Run(
        task_name=f"run-{uuid.uuid4().hex[:6]}", owner_id=owner_id,
        evaluator_id=evaluator_id, dataset_id=dataset_id,
        flow_template_id=template_id, mode="exec", status=status,
        total_cases=total_cases, extra_metric_ids=[],
        round_size=round_size, total_rounds=total_rounds,
        done_rounds=0,
    )
    db.add(run)
    db.flush()
    return run


def _case_results(db, run_id, case_ids):
    """批量建 CaseResult(pending)。"""
    for cid in case_ids:
        db.add(CaseResult(run_id=run_id, case_id=cid, status="pending"))
    db.flush()


# ---------- 测试 ----------

class TestRoundSplitting:
    """创建任务时 round_size 切分。"""

    def test_split_10_by_3(self, db):
        """10 用例 / round_size=3 → 4 轮：3+3+3+1。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        ds = _dataset_with_cases(db, user.id, 10, round_size=3)
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()

        # 验证 round_no 分配
        expected = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3]
        actual = [c.round_no for c in cases]
        assert actual == expected

        # total_rounds = ceil(10/3) = 4
        total_rounds = -(-10 // 3)
        assert total_rounds == 4

    def test_split_exact(self, db):
        """9 用例 / round_size=3 → 3 轮：3+3+3。"""
        user = _user(db)
        ds = _dataset_with_cases(db, user.id, 9, round_size=3)
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        expected = [0, 0, 0, 1, 1, 1, 2, 2, 2]
        assert [c.round_no for c in cases] == expected
        assert -(-9 // 3) == 3

    def test_split_1(self, db):
        """round_size=1 → 每轮 1 个用例。"""
        user = _user(db)
        ds = _dataset_with_cases(db, user.id, 5, round_size=1)
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        assert [c.round_no for c in cases] == [0, 1, 2, 3, 4]
        assert -(-5 // 1) == 5

    def test_round_size_1_degrades_to_no_round(self, db):
        """round_size=1 在后端创建任务时退化为 None（无轮次模式）。"""
        # 模拟 create_run 的逻辑
        round_size = 1
        if round_size is not None and round_size < 1:
            raise ValueError("round_size 必须为正整数")
        if round_size == 1:
            round_size = None
        assert round_size is None

        # 验证：round_size=None 时不设置 round_no
        user = _user(db)
        ds = _dataset_with_cases(db, user.id, 5)  # 无 round_size → 无 round_no
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        assert all(c.round_no is None for c in cases)


class TestClaimRound:
    """claim_round 抢整组。"""

    def test_claim_first_round(self, db):
        """第 0 轮可抢（无前一轮依赖）。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 6, round_size=3)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=6, total_rounds=2, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        result = task_queue.claim_round("w1")
        assert result is not None
        assert result["round_no"] == 0
        assert len(result["case_result_ids"]) == 3
        assert result["run_id"] == str(run.id)

        # 该组 case 已置 running
        for cr_id in result["case_result_ids"]:
            cr = db.get(CaseResult, uuid.UUID(cr_id))
            assert cr.status == "running"
            assert cr.locked_by == "w1"

    def test_claim_round_never_reclaims_executed_cases(self, db):
        """本轮部分 case 已执行完成时，只能 claim 剩余 pending，不能重复执行 executed。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 3, round_size=3)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=3, total_rounds=1, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.flush()

        # 模拟 C001 已经执行完成；C002/C003 仍待执行。
        cr1 = db.query(CaseResult).filter(CaseResult.case_id == cases[0].id).one()
        cr1.status = "executed"
        cr1.agent_output = "already-done"
        cr1.exec_finished_at = _utcnow()
        db.commit()

        result = task_queue.claim_round("w1")
        assert result is not None
        assert len(result["case_result_ids"]) == 2
        claimed = {uuid.UUID(x) for x in result["case_result_ids"]}
        assert cr1.id not in claimed

        db.expire_all()
        cr1_after = db.get(CaseResult, cr1.id)
        assert cr1_after.status == "executed"
        assert cr1_after.agent_output == "already-done"


    def test_claim_second_round_blocked(self, db):
        """第 1 轮被阻塞（第 0 轮未完成）。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 6, round_size=3)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=6, total_rounds=2, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        # 先抢第 0 轮
        r1 = task_queue.claim_round("w1")
        assert r1 is not None and r1["round_no"] == 0

        # 第 1 轮应被阻塞（第 0 轮还在 running）
        r2 = task_queue.claim_round("w2")
        assert r2 is None

    def test_claim_second_round_after_first_done(self, db):
        """第 0 轮完成后，第 1 轮可抢。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 6, round_size=3)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=6, total_rounds=2, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        # 抢第 0 轮
        r1 = task_queue.claim_round("w1")
        assert r1 is not None and r1["round_no"] == 0

        # 模拟第 0 轮完成
        for cr_id in r1["case_result_ids"]:
            cr = db.get(CaseResult, uuid.UUID(cr_id))
            cr.status = "passed"
            cr.finished_at = _utcnow()
        db.commit()

        # 第 1 轮现在可抢
        r2 = task_queue.claim_round("w2")
        assert r2 is not None
        assert r2["round_no"] == 1
        assert len(r2["case_result_ids"]) == 3

    def test_no_round_mode_returns_none(self, db):
        """非轮次模式（round_size=None）→ claim_round 返回 None。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 5)  # 无 round_no
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=None,
                   total_cases=5, total_rounds=None, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        assert task_queue.claim_round("w1") is None

    def test_paused_run_not_claimed(self, db):
        """暂停的 run 不被抢。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 3, round_size=3)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=3, total_rounds=1, status="paused")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        assert task_queue.claim_round("w1") is None


class TestVariableGroupRotation:
    """变量组循环分配。"""

    def test_group_rotation_3_groups_5_rounds(self, db):
        """3 组变量，5 轮 → 组0,组1,组2,组0,组1。"""
        user = _user(db)
        groups = [
            {"phone": "111", "device": "D1"},
            {"phone": "222", "device": "D2"},
            {"phone": "333", "device": "D3"},
        ]
        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {"phone": "{{phone}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        cj = _chain_json(pre_api_groups=groups, pre_api=pre_api)
        tpl = FlowTemplate(name="tpl", chain_json=cj)
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 15, round_size=3)
        run = _run(db, user.id, _std_evaluator(db)[0].id, ds.id, tpl.id,
                   round_size=3, total_cases=15, total_rounds=5, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        # mock 前置 API：返回 {"data": {"sessionId": f"sess-{round_no}"}}
        import app.modules.runs.target_client as tc
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: {"data": {"sessionId": f"sess-{k.get('variables', {}).get('phone', '?')}"}}

        try:
            r = db.bind  # 用 FakeRedis（autouse fixture）
            import app.core.redis_client as rc
            fake_r = rc._redis

            expected_groups = [0, 1, 2, 0, 1]
            for round_no in range(5):
                vars_ = get_group_variables(str(run.id), round_no, cj, fake_r)
                # 验证变量组正确
                assert vars_["phone"] == groups[expected_groups[round_no]]["phone"]
                assert vars_["device"] == groups[expected_groups[round_no]]["device"]
                # 验证 session_id 被提取
                assert "session_id" in vars_
                # 验证 session_id 对应正确的 phone
                expected_phone = groups[expected_groups[round_no]]["phone"]
                assert vars_["session_id"] == f"sess-{expected_phone}"
        finally:
            tc.call_pre_api = orig_call_pre_api

    def test_group_rotation_2_groups_5_rounds(self, db):
        """2 组变量，5 轮 → 组0,组1,组0,组1,组0。"""
        groups = [
            {"phone": "A"},
            {"phone": "B"},
        ]
        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {"phone": "{{phone}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        cj = _chain_json(pre_api_groups=groups, pre_api=pre_api)

        import app.modules.runs.target_client as tc
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: {"data": {"sessionId": f"sess-{k.get('variables', {}).get('phone', '?')}"}}

        try:
            import app.core.redis_client as rc
            fake_r = rc._redis

            expected = ["A", "B", "A", "B", "A"]
            for i, round_no in enumerate(range(5)):
                rid = str(uuid.uuid4())
                vars_ = get_group_variables(rid, round_no, cj, fake_r)
                assert vars_["phone"] == expected[i], f"round {round_no}: expected {expected[i]}, got {vars_['phone']}"
        finally:
            tc.call_pre_api = orig_call_pre_api


class TestEnsureSession:
    """ensure_session 缓存 + 过期刷新。"""

    def test_cache_hit(self, db):
        """缓存命中且 TTL 充足 → 不重新调前置 API。"""
        import app.core.redis_client as rc
        fake_r = rc._redis

        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {"phone": "{{phone}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        groups = [{"phone": "111"}]
        cj = _chain_json(pre_api_groups=groups, pre_api=pre_api)

        import app.modules.runs.target_client as tc
        call_count = [0]
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: (call_count.__setitem__(0, call_count[0] + 1),
                                           {"data": {"sessionId": f"sess-{call_count[0]}"}})[1]

        try:
            rid = str(uuid.uuid4())
            # 第一次：缓存不存在 → 调前置 API
            v1 = ensure_session(rid, 0, cj, fake_r)
            assert call_count[0] == 1
            assert v1["session_id"] == "sess-1"
            assert v1["phone"] == "111"

            # 第二次：缓存命中（TTL=3600 > 60）→ 不调前置 API
            v2 = ensure_session(rid, 0, cj, fake_r)
            assert call_count[0] == 1  # 没增加
            assert v2["session_id"] == "sess-1"
        finally:
            tc.call_pre_api = orig_call_pre_api

    def test_cache_expired_refresh(self, db):
        """缓存快过期（TTL < 60s）→ 重新调前置 API。"""
        import app.core.redis_client as rc
        fake_r = rc._redis

        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {"phone": "{{phone}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        groups = [{"phone": "111"}]
        cj = _chain_json(pre_api_groups=groups, pre_api=pre_api)

        import app.modules.runs.target_client as tc
        call_count = [0]
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: (call_count.__setitem__(0, call_count[0] + 1),
                                           {"data": {"sessionId": f"sess-{call_count[0]}"}})[1]

        try:
            rid = str(uuid.uuid4())
            # 第一次：调前置 API
            v1 = ensure_session(rid, 0, cj, fake_r)
            assert call_count[0] == 1

            # 手动把 TTL 改成 30s（模拟快过期）
            cache_key = f"agent_eval:session:{rid}:0"
            fake_r._ttl[cache_key] = 30

            # 第二次：TTL=30 < 60 → 刷新
            v2 = ensure_session(rid, 0, cj, fake_r)
            assert call_count[0] == 2
            assert v2["session_id"] == "sess-2"
            # 变量组不变
            assert v2["phone"] == "111"
        finally:
            tc.call_pre_api = orig_call_pre_api

    def test_no_pre_api_returns_empty(self, db):
        """无前置 API → 返回空 dict。"""
        import app.core.redis_client as rc
        fake_r = rc._redis
        cj = _chain_json()  # 无 pre_api
        assert ensure_session(str(uuid.uuid4()), 0, cj, fake_r) == {}


class TestProcessRound:
    """process_round 全链路（mock 外部调用）。"""

    def test_full_round_execution(self, db, monkeypatch):
        """完整执行一轮：3 个 case 串行 + 变量组 + session 缓存。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)

        groups = [
            {"phone": "111", "device": "D1"},
            {"phone": "222", "device": "D2"},
        ]
        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {"phone": "{{phone}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        cj = _chain_json(pre_api_groups=groups, pre_api=pre_api,
                         variables={"app": "test"})
        tpl = FlowTemplate(name="tpl", chain_json=cj)
        db.add(tpl)
        db.flush()

        ds = _dataset_with_cases(db, user.id, 6, round_size=3)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=6, total_rounds=2, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        # mock 外部调用
        import app.modules.runs.target_client as tc
        import app.modules.runs.worker as w

        pre_api_calls = []
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: (
            pre_api_calls.append(k.get("variables", {})),
            {"data": {"sessionId": f"sess-{k.get('variables', {}).get('phone', '?')}"}}
        )[1]

        agent_calls = []
        orig_call_target = w.call_target_multi_turn
        w.call_target_multi_turn = lambda chain, row, **kw: (
            agent_calls.append(dict(row)),
            f"MOCK-{row.get('case_no', '')}"
        )[1]

        orig_score = w.score_all_metrics
        w.score_all_metrics = lambda *a, **k: {
            "standard_metrics": [{"metric_id": m["id"], "score": 80, "reason": "ok"} for m in a[1]],
            "extra_metrics": [],
            "brief_comment": "",
            "failure_attribution": None,
            "usage": {"total_tokens": 10},
            "latency_sec": 0.1,
        }

        try:
            # 抢第 0 轮
            r0 = task_queue.claim_round("w1")
            assert r0 is not None and r0["round_no"] == 0
            assert len(r0["case_result_ids"]) == 3

            # 执行第 0 轮（执行与评分解耦：执行后 case 置 executed，评分异步）
            w.process_round(r0)

            # 验证：前置 API 调了 1 次（组内 3 个 case 共享 session）
            # 注意：ensure_session 每个 case 前调一次，但缓存命中后不重新调
            # 第一次 case1: 缓存不存在 → 调前置 API
            # 第二次 case2: 缓存命中（TTL=3600 > 60）→ 不调
            # 第三次 case3: 缓存命中 → 不调
            assert len(pre_api_calls) == 1
            assert pre_api_calls[0]["phone"] == "111"  # 组 0

            # 验证：被测 Agent 调了 3 次（组内串行）
            assert len(agent_calls) == 3
            # 每次调用都带 session_id
            for call in agent_calls:
                assert call["session_id"] == "sess-111"
                assert call["phone"] == "111"
                assert call["device"] == "D1"

            # 验证：执行完成，case 状态为 executed（待评分）
            for cr_id in r0["case_result_ids"]:
                cr = db.get(CaseResult, uuid.UUID(cr_id))
                assert cr.status == "executed"
                assert cr.agent_output is not None

            # 验证：run 计数（done_rounds 在执行阶段递增；done_cases 待评分后才到终态）
            db.refresh(run)
            assert run.done_rounds == 1

            # 抢第 1 轮（第 0 轮执行已完成，done_rounds 递增后前一轮屏障放行）
            r1 = task_queue.claim_round("w2")
            assert r1 is not None and r1["round_no"] == 1

            # 执行第 1 轮
            w.process_round(r1)

            # 验证：前置 API 又调了 1 次（不同 round_no → 不同缓存 key）
            assert len(pre_api_calls) == 2
            assert pre_api_calls[1]["phone"] == "222"  # 组 1

            # 异步评分：把所有 executed case 评分到终态
            _drain_scoring(w, task_queue, db)

            # 验证：run 完成（评分结束才 done）
            db.refresh(run)
            assert run.status == "done"
            assert run.done_rounds == 2
            assert run.done_cases == 6
            for cr in db.query(CaseResult).filter(CaseResult.run_id == run.id).all():
                assert cr.status in ("passed", "failed")
                assert cr.finished_at is not None
        finally:
            tc.call_pre_api = orig_call_pre_api
            w.call_target_multi_turn = orig_call_target
            w.score_all_metrics = orig_score


class TestRoundOrdering:
    """轮次分组 + 组内顺序执行验证（round_size=5 实际场景）。"""

    def test_round_size_5_grouping_and_order(self, db, monkeypatch):
        """round_size=5，12 个 case → 3 组（5+5+2）。

        验证：
        1. round_no 分配：case 1-5→0, 6-10→1, 11-12→2
        2. 每组内 case 按 sort_order 串行执行（mock 记录调用顺序）
        3. 组间串行（前一组执行完才执行下一组）
        """
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl); db.flush()
        # 12 个 case，round_size=5 → round_no: [0]*5 + [1]*5 + [2]*2
        ds = _dataset_with_cases(db, user.id, 12, round_size=5)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=5,
                   total_cases=12, total_rounds=3, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        # 验证 round_no 分配
        assert [c.round_no for c in cases] == [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2]

        import app.modules.runs.worker as w
        exec_order: list[str] = []  # 记录实际执行顺序（case_no）
        orig_call_target = w.call_target_multi_turn
        w.call_target_multi_turn = lambda chain, row, **kw: (
            exec_order.append(row.get("case_no", "")),
            f"OUT-{row.get('case_no', '')}"
        )[1]
        orig_score = w.score_all_metrics
        w.score_all_metrics = lambda *a, **k: {
            "standard_metrics": [{"metric_id": m["id"], "score": 80, "reason": "ok"} for m in a[1]],
            "extra_metrics": [],
            "brief_comment": "",
            "failure_attribution": None,
            "usage": {"total_tokens": 1},
            "latency_sec": 0.1,
        }
        try:
            # 逐轮执行（模拟 worker 串行抢轮次）
            for expected_round in (0, 1, 2):
                ri = task_queue.claim_round("w1")
                assert ri is not None, f"第 {expected_round} 轮未被抢到"
                assert ri["round_no"] == expected_round
                w.process_round(ri)

            # 验证执行顺序：组内按 sort_order 串行，组间按轮次顺序
            # 第 0 轮：C001..C005；第 1 轮：C006..C010；第 2 轮：C011..C012
            assert exec_order == [
                "C001", "C002", "C003", "C004", "C005",
                "C006", "C007", "C008", "C009", "C010",
                "C011", "C012",
            ], f"执行顺序错误: {exec_order}"

            # 验证所有 case 执行完（executed），评分到终态
            _drain_scoring(w, task_queue, db)
            db.refresh(run)
            assert run.status == "done"
            assert run.done_cases == 12
        finally:
            w.call_target_multi_turn = orig_call_target
            w.score_all_metrics = orig_score

    def test_round_size_5_last_group_partial(self, db, monkeypatch):
        """round_size=5，7 个 case → 2 组（5+2）。最后一组只有 2 个。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl); db.flush()
        ds = _dataset_with_cases(db, user.id, 7, round_size=5)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=5,
                   total_cases=7, total_rounds=2, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        assert [c.round_no for c in cases] == [0, 0, 0, 0, 0, 1, 1]

        import app.modules.runs.worker as w
        exec_order: list[str] = []
        orig_call_target = w.call_target_multi_turn
        w.call_target_multi_turn = lambda chain, row, **kw: (
            exec_order.append(row.get("case_no", "")), "OUT"
        )[1]
        orig_score = w.score_all_metrics
        w.score_all_metrics = lambda *a, **k: {
            "standard_metrics": [{"metric_id": m["id"], "score": 80, "reason": "ok"} for m in a[1]],
            "extra_metrics": [],
            "brief_comment": "",
            "failure_attribution": None,
            "usage": {"total_tokens": 1},
            "latency_sec": 0.1,
        }
        try:
            r0 = task_queue.claim_round("w1")
            assert r0 is not None and r0["round_no"] == 0
            assert len(r0["case_result_ids"]) == 5  # 第 0 轮 5 个
            w.process_round(r0)

            r1 = task_queue.claim_round("w1")
            assert r1 is not None and r1["round_no"] == 1
            assert len(r1["case_result_ids"]) == 2  # 第 1 轮 2 个（最后一组不满）
            w.process_round(r1)

            assert exec_order == ["C001", "C002", "C003", "C004", "C005", "C006", "C007"]
        finally:
            w.call_target_multi_turn = orig_call_target
            w.score_all_metrics = orig_score


class TestSlotBusyYield:
    """SlotBusy 非阻塞让出：槽位忙 → 回 pending 让出 worker 线程，不 sleep 占线程。"""

    def test_process_case_slotbusy_yields_pending(self, db, monkeypatch):
        """非轮次模式：被测槽位忙 → case 回 pending（让出），不标 error。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl); db.flush()
        ds = _dataset_with_cases(db, user.id, 1)  # 无 round_no
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=None,
                   total_cases=1, total_rounds=None, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        import app.modules.runs.worker as w
        orig = w.call_target_multi_turn
        # mock 抛 SlotBusy（模拟被测并发槽位满）
        w.call_target_multi_turn = lambda *a, **k: (_ for _ in ()).throw(w.SlotBusy("槽位忙"))

        try:
            cr_id = task_queue.claim_case("w1")
            assert cr_id is not None
            w.process_case(cr_id)
            # 让出：case 回 pending，非 error
            cr = db.query(CaseResult).filter(CaseResult.run_id == run.id).first()
            db.expire_all()
            cr = db.query(CaseResult).filter(CaseResult.run_id == run.id).first()
            assert cr.status == "pending"
            assert cr.locked_by is None
        finally:
            w.call_target_multi_turn = orig

    def test_process_round_slotbusy_yields_group(self, db, monkeypatch):
        """轮次模式：被测槽位忙 → 整组回 pending（让出），保序待重抢。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl); db.flush()
        ds = _dataset_with_cases(db, user.id, 3, round_size=3)  # 1 轮 3 case
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=3, total_rounds=1, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        import app.modules.runs.worker as w
        orig = w.call_target_multi_turn
        w.call_target_multi_turn = lambda *a, **k: (_ for _ in ()).throw(w.SlotBusy("槽位忙"))

        try:
            r0 = task_queue.claim_round("w1")
            assert r0 is not None and r0["round_no"] == 0
            w.process_round(r0)
            # 整组让出：3 个 case 全回 pending
            db.expire_all()
            crs = db.query(CaseResult).filter(CaseResult.run_id == run.id).all()
            assert all(cr.status == "pending" for cr in crs)
            assert all(cr.locked_by is None for cr in crs)
            # run 仍 running（未完成）
            db.refresh(run)
            assert run.status == "running"
        finally:
            w.call_target_multi_turn = orig

    def test_slotbusy_yield_limit_marks_error(self, db, monkeypatch):
        """让出超上限（YIELD_LIMIT_MAX）→ 标 error，防活锁。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl); db.flush()
        ds = _dataset_with_cases(db, user.id, 1)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=None,
                   total_cases=1, total_rounds=None, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        import app.modules.runs.worker as w
        import app.core.redis_client as rc
        fake_r = rc._redis
        orig = w.call_target_multi_turn
        w.call_target_multi_turn = lambda *a, **k: (_ for _ in ()).throw(w.SlotBusy("槽位忙"))

        try:
            cr_id = task_queue.claim_case("w1")
            assert cr_id is not None
            # 手动把让出计数推到上限（模拟反复让出）
            fake_r.set(f"agent_eval:yield:{cr_id}", w.YIELD_LIMIT_MAX)
            w.process_case(cr_id)
            # 超上限 → 标 error
            db.expire_all()
            cr = db.query(CaseResult).filter(CaseResult.run_id == run.id).first()
            assert cr.status == "error"
            assert "持续繁忙" in (cr.error_msg or "")
            assert cr.finished_at is not None
        finally:
            w.call_target_multi_turn = orig
            fake_r.delete(f"agent_eval:yield:{cr_id}")


    def test_round_error_marks_all_cases(self, db, monkeypatch):
        """前置 API 失败 → 整组标记 error。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        cj = _chain_json(pre_api=pre_api)
        tpl = FlowTemplate(name="tpl", chain_json=cj)
        db.add(tpl)
        db.flush()

        ds = _dataset_with_cases(db, user.id, 3, round_size=3)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=3,
                   total_cases=3, total_rounds=1, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        import app.modules.runs.target_client as tc
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("timeout"))

        try:
            r0 = task_queue.claim_round("w1")
            assert r0 is not None
            worker.process_round(r0)

            # 整组标记 error
            for cr_id in r0["case_result_ids"]:
                cr = db.get(CaseResult, uuid.UUID(cr_id))
                assert cr.status == "error"
                assert "timeout" in (cr.error_msg or "")

            db.refresh(run)
            assert run.done_rounds == 1
        finally:
            tc.call_pre_api = orig_call_pre_api


class TestNonRoundMode:
    """非轮次模式（round_size=None）走原有 claim_case 路径。"""

    def test_claim_case_still_works(self, db):
        """round_size=None → claim_case 正常抢单条 case。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())
        db.add(tpl)
        db.flush()
        ds = _dataset_with_cases(db, user.id, 5)  # 无 round_no
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=None,
                   total_cases=5, total_rounds=None, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        # claim_round 返回 None（无轮次模式）
        assert task_queue.claim_round("w1") is None

        # claim_case 正常抢
        cr_id = task_queue.claim_case("w1")
        assert cr_id is not None
        cr = db.get(CaseResult, uuid.UUID(cr_id))
        assert cr.status == "running"


class TestPreApiWithoutRounds:
    """前置 API 与轮次解耦：无轮次模式 + 前置 API。"""

    def test_global_session_shared(self, db, monkeypatch):
        """无轮次 + 前置 API → 所有 case 共享一个 session（scope_key=global）。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)

        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {"phone": "{{phone}}"},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        cj = _chain_json(pre_api=pre_api, variables={"phone": "111"})
        tpl = FlowTemplate(name="tpl", chain_json=cj)
        db.add(tpl)
        db.flush()

        ds = _dataset_with_cases(db, user.id, 3)  # 无 round_no
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=None,
                   total_cases=3, total_rounds=None, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        import app.modules.runs.target_client as tc
        import app.modules.runs.worker as w

        pre_api_calls = []
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: (
            pre_api_calls.append(k.get("variables", {})),
            {"data": {"sessionId": f"sess-{len(pre_api_calls)}"}}
        )[1]

        agent_calls = []
        orig_call_target = w.call_target_multi_turn
        w.call_target_multi_turn = lambda chain, row, **kw: (
            agent_calls.append(dict(row)),
            f"MOCK-{row.get('case_no', '')}"
        )[1]

        orig_score = w.score_all_metrics
        w.score_all_metrics = lambda *a, **k: {
            "standard_metrics": [{"metric_id": m["id"], "score": 80, "reason": "ok"} for m in a[1]],
            "extra_metrics": [],
            "brief_comment": "",
            "failure_attribution": None,
            "usage": {"total_tokens": 10},
            "latency_sec": 0.1,
        }

        try:
            # 执行 3 个 case（claim_case 逐个抢）
            for _ in range(3):
                cr_id = task_queue.claim_case("w1")
                assert cr_id is not None
                w.process_case(cr_id)

            # 前置 API 只调了 1 次（所有 case 共享 global session）
            assert len(pre_api_calls) == 1
            assert pre_api_calls[0]["phone"] == "111"

            # 被测 Agent 调了 3 次，每次都带同一个 session_id
            assert len(agent_calls) == 3
            # 前置 API 只调了 1 次 → sessionId = "sess-1"（append 后 len=1）
            for call in agent_calls:
                assert call["session_id"] == "sess-1"

            # 执行完成，case 为 executed；异步评分到终态后 run 才 done
            _drain_scoring(w, task_queue, db)
            db.refresh(run)
            assert run.status == "done"
            assert run.done_cases == 3
        finally:
            tc.call_pre_api = orig_call_pre_api
            w.call_target_multi_turn = orig_call_target
            w.score_all_metrics = orig_score

    def test_no_pre_api_no_session(self, db, monkeypatch):
        """无轮次 + 无前置 API → 不调前置 API，row 无 session 变量。"""
        user = _user(db)
        ev, _ = _std_evaluator(db)
        tpl = FlowTemplate(name="tpl", chain_json=_chain_json())  # 无 pre_api
        db.add(tpl)
        db.flush()

        ds = _dataset_with_cases(db, user.id, 2)
        run = _run(db, user.id, ev.id, ds.id, tpl.id, round_size=None,
                   total_cases=2, total_rounds=None, status="running")
        cases = db.query(Case).filter(Case.dataset_id == ds.id).order_by(Case.sort_order).all()
        _case_results(db, run.id, [c.id for c in cases])
        db.commit()

        import app.modules.runs.target_client as tc
        import app.modules.runs.worker as w

        pre_api_calls = []
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: (
            pre_api_calls.append(1),
            {"data": {"sessionId": "should-not-be-called"}}
        )[1]

        agent_calls = []
        orig_call_target = w.call_target_multi_turn
        w.call_target_multi_turn = lambda chain, row, **kw: (
            agent_calls.append(dict(row)),
            "MOCK"
        )[1]

        orig_score = w.score_all_metrics
        w.score_all_metrics = lambda *a, **k: {
            "standard_metrics": [{"metric_id": m["id"], "score": 80, "reason": "ok"} for m in a[1]],
            "extra_metrics": [],
            "brief_comment": "",
            "failure_attribution": None,
            "usage": {"total_tokens": 10},
            "latency_sec": 0.1,
        }

        try:
            for _ in range(2):
                cr_id = task_queue.claim_case("w1")
                w.process_case(cr_id)

            # 前置 API 没被调
            assert len(pre_api_calls) == 0
            # row 里没有 session_id
            for call in agent_calls:
                assert "session_id" not in call
        finally:
            tc.call_pre_api = orig_call_pre_api
            w.call_target_multi_turn = orig_call_target
            w.score_all_metrics = orig_score

    def test_ensure_session_global_scope(self, db):
        """ensure_session scope_key='global' → 缓存 key 含 'global'。"""
        import app.core.redis_client as rc
        fake_r = rc._redis

        pre_api = {
        "enabled": True,
            "method": "POST", "url": "http://mock/session",
            "body": {},
            "extract": {"session_id": "data.sessionId"},
            "ttl_seconds": 3600,
        }
        cj = _chain_json(pre_api=pre_api)

        import app.modules.runs.target_client as tc
        orig_call_pre_api = tc.call_pre_api
        tc.call_pre_api = lambda *a, **k: {"data": {"sessionId": "global-sess"}}

        try:
            rid = str(uuid.uuid4())
            v = ensure_session(rid, "global", cj, fake_r)
            assert v["session_id"] == "global-sess"

            # 验证缓存 key
            cache_key = f"agent_eval:session:{rid}:global"
            assert fake_r.get(cache_key) is not None
        finally:
            tc.call_pre_api = orig_call_pre_api

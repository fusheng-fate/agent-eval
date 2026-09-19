"""任务队列（PG case_results 表）。

队列 = case_results 中 status='pending' 且所属 run.status='running' 的行。
worker 用 SELECT ... FOR UPDATE SKIP LOCKED 原子抢任务（PG），SQLite 方言下
退化为普通 SELECT（测试单线程无竞争，结果正确）。

轮次模式（round_size 非空）：
  - 队列单位从"单条 case"升级为"整组轮次"
  - claim_round 抢一个可执行的轮次（该组所有 case 都是 pending）
  - 组内 case 由 worker 串行执行，组间按 target_concurrency 并发

非轮次模式（round_size 为空）：
  - 保持原有行为，claim_case 抢单条 pending case
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update

from ...core.database import SessionLocal
from ...models import Case, CaseResult, Run

log = logging.getLogger("queue")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_case(worker_id: str) -> str | None:
    """原子抢一条 pending case，返回 case_result.id（str）；无则 None。

    非轮次模式专用。只抢所属 run.status='running' 且 Case.round_no IS NULL 的 case。
    轮次 case（round_no 非空）由 claim_round 整组调度，claim_case 绝不触碰，
    防止轮次 case 被单独抢走破坏组内顺序。
    """
    db = SessionLocal()
    try:
        is_pg = db.bind.dialect.name == "postgresql"
        now = _utcnow()
        sub = (
            select(CaseResult.id)
            .join(Run, CaseResult.run_id == Run.id)
            .join(Case, CaseResult.case_id == Case.id)
            .where(
                CaseResult.status == "pending",
                Run.status == "running",
                Case.round_no.is_(None),
                # 退避过滤：locked_at 为未来时间（让出退避中）的 case 跳过
                or_(CaseResult.locked_at.is_(None), CaseResult.locked_at < now),
            )
            .order_by(CaseResult.id)
            .limit(1)
        )
        if is_pg:
            sub = sub.with_for_update(skip_locked=True)
        row_id = db.execute(sub).scalar_one_or_none()
        if row_id is None:
            return None
        db.execute(
            update(CaseResult)
            .where(CaseResult.id == row_id)
            .values(status="running", locked_by=worker_id, locked_at=_utcnow())
        )
        db.commit()
        return str(row_id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def claim_round(worker_id: str) -> dict | None:
    """原子抢一个可执行轮次，只抢该轮当前仍为 pending 的 CaseResult。

    关键保证：同一 round 如果已有 running case，则不允许另一个 worker
    把剩余 pending case 再抢走；否则会造成同一轮并发执行。已经 executed /
    passed / failed / error 的 CaseResult 也绝不会被重新置为 running。
    """
    db = SessionLocal()
    try:
        is_pg = db.bind.dialect.name == "postgresql"
        now = _utcnow()

        has_round_runs = (
            db.query(Run.id)
            .filter(Run.status == "running", Run.round_size.isnot(None))
            .first()
        )
        if not has_round_runs:
            return None

        pending_groups = (
            db.query(CaseResult.run_id, CaseResult.case_id)
            .join(Run, CaseResult.run_id == Run.id)
            .join(Case, CaseResult.case_id == Case.id)
            .filter(
                CaseResult.status == "pending",
                Run.status == "running",
                Case.round_no.isnot(None),
                or_(CaseResult.locked_at.is_(None), CaseResult.locked_at < now),
            )
            .all()
        )
        if not pending_groups:
            return None

        from collections import defaultdict
        groups: dict[tuple, list] = defaultdict(list)
        for run_id, case_id in pending_groups:
            case = db.get(Case, case_id)
            if case is not None and case.round_no is not None:
                groups[(run_id, case.round_no)].append(case_id)

        for (run_id, round_no), _pending_case_ids in sorted(
            groups.items(), key=lambda x: (x[0][0], x[0][1])
        ):
            run = db.get(Run, run_id)
            if run is None or run.status != "running" or run.round_size is None:
                continue

            # 当前轮必须没有正在执行的 case。这样即使本轮之前发生了 error，
            # 剩余 pending 可以重试；但绝不会让两个 worker 同时执行同一轮。
            inflight = (
                db.query(CaseResult)
                .join(Case, CaseResult.case_id == Case.id)
                .filter(
                    CaseResult.run_id == run_id,
                    Case.dataset_id == run.dataset_id,
                    Case.round_no == round_no,
                    CaseResult.status.in_(["running", "scoring"]),
                )
                .count()
            )
            if inflight > 0:
                continue

            # 只获取本轮 pending 的 CaseResult。绝不能把 executed/failed/error
            # 等已经处理过的结果重新改成 running。
            q = (
                db.query(CaseResult)
                .join(Case, CaseResult.case_id == Case.id)
                .filter(
                    CaseResult.run_id == run_id,
                    Case.dataset_id == run.dataset_id,
                    Case.round_no == round_no,
                    CaseResult.status == "pending",
                    or_(CaseResult.locked_at.is_(None), CaseResult.locked_at < now),
                )
            )
            if is_pg:
                q = q.with_for_update(skip_locked=True)
            cr_rows = q.order_by(CaseResult.id).all()
            if not cr_rows:
                continue

            # PostgreSQL 下，如果本轮还有其它 pending 行正被另一个 worker 锁住，
            # 本次不要只抢到“半组”，否则会破坏组内串行语义。
            expected_pending = len(_pending_case_ids)
            if is_pg and len(cr_rows) < expected_pending:
                db.rollback()
                continue

            claimed_at = _utcnow()
            for cr in cr_rows:
                cr.status = "running"
                cr.locked_by = worker_id
                cr.locked_at = claimed_at
            db.commit()

            return {
                "run_id": str(run_id),
                "round_no": round_no,
                "case_result_ids": [str(cr.id) for cr in cr_rows],
            }

        return None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def heartbeat_case_results(worker_id: str, case_result_ids: list[str]) -> int:
    """刷新 worker 持有的 running/scoring case 租约。使用独立 DB session，
    因为真正的 Agent/LLM 调用可能长时间阻塞当前 worker 线程。
    """
    if not case_result_ids:
        return 0
    db = SessionLocal()
    try:
        from uuid import UUID
        ids = [UUID(str(x)) for x in case_result_ids]
        res = db.execute(
            update(CaseResult)
            .where(
                CaseResult.id.in_(ids),
                CaseResult.locked_by == worker_id,
                CaseResult.status.in_(["running", "scoring"]),
            )
            .values(locked_at=_utcnow())
        )
        db.commit()
        return res.rowcount or 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def claim_score_task(worker_id: str) -> str | None:
    """原子抢一条待评分 case（status='executed'），返回 case_result.id（str）；无则 None。

    评分池专用。与执行解耦：只抢已执行完成（agent_output 已落库）的 case，
    不检查 round_no/组状态（评分不依赖组顺序，可并发）。
    抢到后置 scoring + 记锁，供 process_score 评分。
    """
    db = SessionLocal()
    try:
        is_pg = db.bind.dialect.name == "postgresql"
        now = _utcnow()
        sub = (
            select(CaseResult.id)
            .join(Run, CaseResult.run_id == Run.id)
            .where(
                CaseResult.status == "executed",
                Run.status == "running",
                # 退避过滤：让出退避中的 case 跳过
                or_(CaseResult.locked_at.is_(None), CaseResult.locked_at < now),
            )
            .order_by(CaseResult.id)
            .limit(1)
        )
        if is_pg:
            sub = sub.with_for_update(skip_locked=True)
        row_id = db.execute(sub).scalar_one_or_none()
        if row_id is None:
            return None
        db.execute(
            update(CaseResult)
            .where(CaseResult.id == row_id)
            .values(status="scoring", locked_by=worker_id, locked_at=_utcnow())
        )
        db.commit()
        return str(row_id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def recover_stale_running(max_age_sec: int = 600) -> int:
    """回收崩溃 worker 遗留的 running / scoring / error case（locked_at 超时 → 回退重跑）。

    worker 进程崩溃/重启后，被它抢走但未完成的 case 可能卡在：
    - running：执行 worker 抢到锁后崩溃，未及写结果 → 回 pending 重新执行
    - scoring：评分 worker 抢到锁后崩溃，未及写分数 → 回 executed 重新评分
      （agent_output 已落库，无需重执行，只重评）
    - error：旧代码 worker 写了 error 但进程崩溃，未及递增计数 / 未 commit → 回 pending
    有 finished_at 的行视为真实完成（worker 已正常落库），不回收。
    executed 态不回收：它是"执行完待评分"的正常中间态，由评分池正常抢占，
    只有 scoring 态（评分中崩溃）才需回收。
    返回回收条数。
    """
    db = SessionLocal()
    try:
        cutoff = _utcnow() - timedelta(seconds=max_age_sec)
        # running / error → pending（重新执行）
        res1 = db.execute(
            update(CaseResult)
            .where(
                CaseResult.status.in_(["running", "error"]),
                CaseResult.locked_at < cutoff,
                CaseResult.finished_at.is_(None),
            )
            .values(status="pending", locked_by=None, locked_at=None)
        )
        # scoring → executed（重新评分，agent_output 已落库）
        res2 = db.execute(
            update(CaseResult)
            .where(
                CaseResult.status == "scoring",
                CaseResult.locked_at < cutoff,
                CaseResult.finished_at.is_(None),
            )
            .values(status="executed", locked_by=None, locked_at=None)
        )
        db.commit()
        return (res1.rowcount or 0) + (res2.rowcount or 0)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def pending_count() -> int:
    """当前队列长度（pending 行数），供看板/诊断。"""
    db = SessionLocal()
    try:
        return db.execute(
            select(func.count())
            .select_from(CaseResult)
            .where(CaseResult.status == "pending")
        ).scalar() or 0
    finally:
        db.close()

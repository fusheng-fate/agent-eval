"""执行 worker：从队列取 case → 调被测 Agent → 拼 prompt 调 LLM → 落库。

核心保证（长程任务）：
- 每条 case 独立落库（case_results），worker 崩溃/重启不丢已完成结果。
- 断点续跑：启动时把 running 态 run 的未完成 case 重新入队。
- 暂停：run.status=paused 时 worker 跳过该 run 的 case（重新入队，不执行）。
- 停止：run.status=stopped 时 worker 丢弃该 run 的 case。
- 并发限流：模型并发 / 待测系统并发用 Redis 计数信号量（P21 上限来自配置）。

轮次模式（round_size 非空）：
- 队列单位从"单条 case"升级为"整组轮次"
- 组内 case 串行执行（有对话前后依赖）
- 组间按 target_concurrency 并发
- 每组开始前调前置 API 获取 session（Redis 缓存带 TTL）
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import SessionLocal
from ...core.redis_client import get_redis
from ...models import Case, CaseResult, Config, Evaluator, EvaluatorMetric, FlowTemplate, Metric, Run, RunLog
from . import task_queue
from .llm_client import build_score_prompt, resolve_llm_token, score_all_metrics
from .target_client import apply_overrides, call_target_multi_turn, ensure_case_session, ensure_session, pre_api_enabled

log = logging.getLogger("worker")

_stop_flag = threading.Event()


class SlotBusy(Exception):
    """并发槽位忙（被测 Agent / LLM 并发上限已满）。

    非阻塞让出信号：_acquire_limit 抢不到槽位时抛出，调用方应把 case 回 pending
    （执行）/ executed（评分）让出 worker 线程，而非原地 sleep 等待。
    槽位空了，队列会重新调度该 case。避免 worker 线程被 sleep 占住导致池子耗尽死锁。
    """


def _utcnow():
    return datetime.now(timezone.utc)


def _write_log(db: Session, run_id, level: str, message: str) -> None:
    """写入一条任务日志（不 commit，由调用方统一提交）。"""
    db.add(RunLog(run_id=run_id, level=level, message=message))


# 终态：评分结束（或执行失败/跳过）后到达，不再变化
_TERMINAL_STATUSES = ["passed", "failed", "error", "skipped"]
# 中间态：执行中/待评分/评分中，run 需等这些清空才 done
_INTERMEDIATE_STATUSES = ["pending", "running", "executed", "scoring"]


def _sync_run_counters(db: Session, run_id) -> None:
    """从 case_results 表实时 COUNT 同步 run 的 done/passed/failed 计数。

    替代 +1 累加，避免暂停/继续/重试导致重复计数。
    单条 SQL（COUNT FILTER）一次出 3 个数，索引扫描 run_id，几十万行也无压力。

    done = 终态 case 数（passed/failed/error/skipped）。
    执行与评分解耦后，case 会经过 executed/scoring 中间态，
    run 完成判定（_try_complete_run）改为"无中间态 case"，见该函数。
    """
    db.flush()  # 确保 cr.status 等变更已写入 DB
    row = db.execute(
        select(
            func.count(CaseResult.id).filter(
                CaseResult.status.in_(_TERMINAL_STATUSES)
            ).label("done"),
            func.count(CaseResult.id).filter(
                CaseResult.status == "passed"
            ).label("passed"),
            func.count(CaseResult.id).filter(
                CaseResult.status == "failed"
            ).label("failed"),
        ).where(CaseResult.run_id == run_id)
    ).one()
    db.execute(
        update(Run).where(Run.id == run_id)
        .values(done_cases=row.done, passed_cases=row.passed, failed_cases=row.failed)
    )
    # expire 让 Run ORM 对象下次访问时从 DB 重新读取，避免 commit 时旧值覆盖
    run_obj = db.get(Run, run_id)
    if run_obj:
        db.expire(run_obj, ["done_cases", "passed_cases", "failed_cases"])


def _clear_result_fields(cr: CaseResult) -> None:
    """清空 case 的结果字段（不 commit，由调用方统一提交）。

    用于异常路径：case 置 error 时，清掉上一轮/部分执行残留的分数与评价，
    避免异常用例带着脏数据（如旧 overall_score）显示，误导用户以为它正常跑完。
    error_msg 由调用方按错误内容单独设置，这里不动。
    """
    cr.overall_score = None
    cr.standard_metrics = None
    cr.extra_metrics = None
    cr.brief_comment = None
    cr.failure_attribution = None
    cr.token_usage = None
    cr.latency_sec = None
    cr.raw_llm = None
    cr.target_trace = None
    # 注意：agent_output 不在此清空。eval_import 模式下 agent_output 是导入时预填的，
    # 由 _score_case 按模式决定是否重置（exec 模式每次重调被测 Agent 会覆盖）。


def _fmt_json(v) -> str:
    """把任意值格式化成多行 JSON 文本（str 原样，None → 空）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, indent=2)
    except Exception:
        return str(v)


def _log_api_call(db: Session, run_id, label: str, step_idx: int, t: dict) -> None:
    """把一次被测 API 调用的详细输入/输出写进任务日志（多行，前端按行渲染）。

    t 来自 target_client 的 trace 条目：{method, url, headers, query, body, status, error, response}。
    """
    lines = [f"── 被测 API 调用 [{label}] (第 {step_idx} 步) ──"]
    lines.append(f"请求: {t.get('method')} {t.get('url')}")
    if t.get("headers"):
        lines.append("Headers:")
        lines.append(_fmt_json(t["headers"]))
    if t.get("query"):
        lines.append("Query:")
        lines.append(_fmt_json(t["query"]))
    if t.get("body"):
        lines.append("Body:")
        lines.append(_fmt_json(t["body"]))
    status = t.get("status")
    lines.append(f"响应状态: {status if status is not None else 'N/A'}")
    if t.get("error"):
        lines.append("错误:")
        lines.append(str(t["error"]))
    if t.get("response") is not None:
        lines.append("响应:")
        lines.append(_fmt_json(t["response"]))
    _write_log(db, run_id, "info", "\n".join(lines))


def _log_llm_call(db: Session, run_id, label: str, metric_name: str, prompt: str, resp: dict) -> None:
    """把一次 LLM 评分调用的详细输入/输出写进任务日志。

    resp 来自 score_all_metrics：{standard_metrics: [], extra_metrics: [], brief_comment, failure_attribution, usage, latency_sec}。
    """
    lines = [f"── LLM 评分调用 [{label}] 指标「{metric_name}」 ──"]
    lines.append("输入 Prompt:")
    lines.append(prompt)
    lines.append("输出:")
    out = {
        "standard_metrics": resp.get("standard_metrics", []),
        "extra_metrics": resp.get("extra_metrics", []),
        "brief_comment": resp.get("brief_comment"),
    }
    if resp.get("failure_attribution"):
        out["failure_attribution"] = resp["failure_attribution"]
    lines.append(_fmt_json(out))
    usage = resp.get("usage") or {}
    if usage:
        lines.append(f"tokens={usage.get('total_tokens', 0)}  latency={resp.get('latency_sec', 0)}s")
    _write_log(db, run_id, "info", "\n".join(lines))


def _load_llm_config(db: Session) -> dict:
    """从 configs 表读 LLM 配置（缺省用 settings）。"""
    def _get(key: str, default):
        row = db.query(Config).filter(Config.config_key == key).first()
        if row and row.config_value:
            cv = row.config_value
            # 兼容两种存储格式：{"value": X}（seed/字符串配置）与裸 dict（前端保存的 llm.auth）
            if isinstance(cv, dict) and "value" in cv:
                return cv["value"]
            return cv
        return default
    return {
        "base_url": _get("llm.base_url", settings.LLM_BASE_URL),
        "api_key": _get("llm.api_key", settings.LLM_API_KEY),
        "model": _get("llm.model", settings.LLM_MODEL),
        "max_tokens": _get("llm.max_tokens", settings.LLM_MAX_TOKENS),
        "timeout": _get("llm.timeout", settings.LLM_TIMEOUT),
        "retry_count": _get("llm.retry_count", settings.LLM_RETRY_COUNT),
        "retry_backoff": _get("llm.retry_backoff", settings.LLM_RETRY_BACKOFF),
        "auth": _get("llm.auth", None),
    }


def _acquire_limit(r, key: str, limit: int, timeout: float = 30.0) -> bool:
    """并发计数限流（Redis INCR/DECR），阻塞等待 + 超时。

    计数 key = 当前占用槽位数；上限 = limit。
    acquire: INCR，若 > limit 则 DECR 回退；
    release: DECR。
    抢到槽位返回 True；超时仍未抢到返回 False（调用方抛 SlotBusy 让出）。

    timeout 默认 30s：在超时窗口内短间隔轮询等待槽位释放（每 0.2s 重试一次），
    覆盖一次被测 Agent / LLM 调用的典型耗时，避免抢不到槽位就立刻回 pending
    造成活锁（槽位忙时多 worker 反复争抢空转，谁都不推进）。
    只有超过 timeout 仍拿不到才返回 False，由调用方按原逻辑让出 + 退避。

    计数加 TTL 兜底：防止 worker 在 acquire 后、release 前崩溃导致计数永久泄漏，
    槽位被永远占满 → 后续所有 case 永久 SlotBusy 死锁（需重启清 Redis 才恢复）。
    TTL 与崩溃回收阈值 STALE_RUNNING_MAX_AGE_SEC 对齐，超过即自动过期复位计数，
    recover_stale_running 同时把卡住的 case 回 pending，两相配合自愈。
    """
    limit = int(limit)
    if limit <= 0:
        return True
    cnt_key = f"{key}:count"
    ttl = max(settings.STALE_RUNNING_MAX_AGE_SEC, 60)
    deadline = time.monotonic() + timeout
    while True:
        cur = r.incr(cnt_key)
        if cur <= limit:
            # 计数上限长期不归零也能自愈：每次成功占用刷新 TTL（崩溃遗忘后过期复位）
            try:
                r.expire(cnt_key, ttl)
            except Exception:
                pass
            return True
        r.decr(cnt_key)
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def _release_limit(r, key: str) -> None:
    """槽位释放：DECR 计数。"""
    cnt_key = f"{key}:count"
    val = r.decr(cnt_key)
    if val < 0:
        r.set(cnt_key, 0)  # 防御：防止异常路径导致计数为负


# SlotBusy 让出上限：超过则标 error，防止槽位长期满时 case 无限让出（活锁）
YIELD_LIMIT_MAX = 10
YIELD_LIMIT_TTL = 3600  # 计数 TTL（秒），case 完成后自然过期
# 让出退避时长（秒）：SlotBusy 让出后 case 在此时间内不被重抢，
# 给占着槽位的 case 时间完成释放槽位，避免反复空转。
YIELD_BACKOFF_SEC = 10


def _incr_yield_count(r, cr_id: str) -> int:
    """累加 case 的 SlotBusy 让出计数，返回当前值。

    防活锁：槽位长期满时 case 反复让出→被抢→再让出，永不执行。
    超过 YIELD_LIMIT_MAX 次后调用方应标 error。
    """
    key = f"agent_eval:yield:{cr_id}"
    val = r.incr(key)
    if val == 1:
        r.expire(key, YIELD_LIMIT_TTL)
    return int(val)


def _clear_yield_count(r, cr_id: str) -> None:
    """case 成功执行/评分后清除让出计数。"""
    r.delete(f"agent_eval:yield:{cr_id}")


class _LeaseHeartbeat:
    """在长时间 Agent/LLM 调用期间刷新 PG worker lease。"""

    def __init__(self, worker_id: str, case_result_ids: list[str]):
        self.worker_id = worker_id
        self.case_result_ids = list(case_result_ids)
        max_age = max(10, int(settings.STALE_RUNNING_MAX_AGE_SEC))
        self.interval = max(5.0, min(30.0, max_age / 3.0))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.case_result_ids or not self.worker_id or self.thread is not None:
            return

        def _loop() -> None:
            while not self.stop_event.is_set():
                try:
                    task_queue.heartbeat_case_results(self.worker_id, self.case_result_ids)
                except Exception:
                    log.warning(
                        "lease heartbeat failed worker=%s case_results=%s",
                        self.worker_id, self.case_result_ids, exc_info=True,
                    )
                if self.stop_event.wait(self.interval):
                    break

        self.thread = threading.Thread(
            target=_loop, name=f"lease-heartbeat-{self.worker_id}", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=max(1.0, self.interval + 1.0))
        self.thread = None


def _execute_case(
    db: Session,
    run: Run,
    cr: CaseResult,
    case: Case,
    row: dict,
    r,
    target_trace: list,
    result_extras: dict,
    effective_chain: dict | None,
) -> float:
    """执行单条 case：调被测 Agent → 落 agent_output + 执行凭证 → 置 executed。

    与评分解耦：本函数只负责"拿 agent_output"，不调 LLM、不算分。
    成功后 cr.status='executed'，由评分池异步评分。
    返回 exec_sec（执行耗时，秒）。

    异常（超时/网络/模板缺失等）向上抛，由调用方（process_round/process_case）
    决定重试或标 error。
    """
    cr.attempt += 1
    # 每次执行从干净状态开始：清掉上一轮/被回收重跑前的残留结果字段，
    # 防止中途异常时残留旧分数/评价混入本次结果。
    _clear_result_fields(cr)
    # exec 模式每次重调被测 Agent，agent_output 会重新生成 → 先清空；
    # eval_import 模式 agent_output 是导入时预填的，保留不动。
    if getattr(run, "mode", "exec") != "eval_import":
        cr.agent_output = None
    _write_log(db, run.id, "info", f"开始执行用例 {case.case_no}")
    db.commit()

    # 1) 拿 agent_output
    _t_exec = time.monotonic()
    cr.exec_started_at = _utcnow()  # 执行开始时刻（调被测 Agent 前）
    if getattr(run, "mode", "exec") == "eval_import":
        agent_output = cr.agent_output or ""
    else:
        # 限流 key 按被测环境（模板）区分：不同流程模板打不同被测系统，并发预算应各自独立，
        # 否则用全局固定 key 会让模板 A（并发 3）与模板 B（并发 5）互相限流/串号。
        # eval_import 无模板时退化回全局 key（不调被测 Agent，实际不会走到这里）。
        template_id = str(run.flow_template_id) if run.flow_template_id else "global"
        agent_output = call_target_multi_turn(
            effective_chain, row,
            limit_key=f"agent_eval:limit:target:{template_id}",
            limit_value=run.target_concurrency,
            r=r,
            trace=target_trace,
            result_extras=result_extras,
        )
    exec_sec = round(time.monotonic() - _t_exec, 2)
    _write_log(db, run.id, "info", f"用例 {case.case_no} 被测 Agent 执行完成，耗时 {exec_sec}s")
    # 输出每步被测 API 的详细输入/输出
    for _i, _t in enumerate(target_trace, 1):
        _log_api_call(db, run.id, case.case_no, _i, _t)

    # 2) 落执行结果：agent_output + 执行凭证 + 执行轨迹 + 耗时
    #    评分字段（overall_score/metrics/comment 等）留空，由 _score_case 填。
    cr.agent_output = agent_output[:20000]
    cr.target_trace = target_trace or None
    cr.node_id = result_extras.get("node_id")
    cr.trace_no = result_extras.get("trace_no")
    cr.exec_finished_at = _utcnow()  # 执行结束时刻（被测 Agent 调用完成、置 executed 前）
    cr.status = "executed"
    # 注意：不设 finished_at（评分结束才设），executed 是中间态
    _sync_run_counters(db, run.id)
    db.execute(
        update(Run)
        .where(Run.id == run.id)
        .values(exec_sec=func.coalesce(Run.exec_sec, 0) + exec_sec)
    )
    db.commit()
    return exec_sec


def _score_case(
    db: Session,
    run: Run,
    cr: CaseResult,
    case: Case,
    row: dict,
    r,
) -> bool:
    """评分单条 case：读已落库的 agent_output → 调 LLM 评分 → 算主分 → 落库 → 置 passed/failed。

    与执行解耦：本函数不调被测 Agent，只调 LLM。由评分池（process_score）调用，
    不依赖组顺序，可并发（受 model_concurrency 限流）。
    返回 passed（True/False）。

    前置：cr.status 应为 'executed' 或 'scoring'，cr.agent_output 已落库。
    异常（LLM 超时等）向上抛，由 process_score 决定重试或标 error。
    """
    agent_output = cr.agent_output or ""

    # 1) 评分：所有指标拼一个 prompt，一次 LLM 调用
    llm_cfg = _load_llm_config(db)
    if llm_cfg.get("auth") is not None:
        _token, _token_query = resolve_llm_token(db, llm_cfg)
        llm_cfg["_token"] = _token
        llm_cfg["_token_query"] = _token_query
        llm_cfg["_db"] = db

    evaluator = db.get(Evaluator, run.evaluator_id)

    # 收集标准指标（含权重 + skill_md）
    std_metric_list = []
    for em in evaluator.metrics:
        metric = db.get(Metric, em.metric_id)
        std_metric_list.append({
            "id": str(metric.id),
            "name": metric.name,
            "weight": float(em.weight),
            "skill_md": metric.skill_md,
        })

    # 收集额外指标
    extra_metric_list = []
    for mid in (run.extra_metric_ids or []):
        metric = db.get(Metric, mid if isinstance(mid, uuid.UUID) else uuid.UUID(mid))
        if metric is None:
            continue
        extra_metric_list.append({
            "id": str(metric.id),
            "name": metric.name,
            "skill_md": metric.skill_md,
        })

    # 一次 LLM 调用评所有指标
    _t_score = time.monotonic()
    if not _acquire_limit(r, "agent_eval:limit:model", run.model_concurrency):
        raise SlotBusy("LLM 并发槽位忙")
    try:
        res = score_all_metrics(llm_cfg, std_metric_list, extra_metric_list, row, agent_output)
    finally:
        _release_limit(r, "agent_eval:limit:model")

    # 日志
    try:
        _prompt = build_score_prompt(std_metric_list, extra_metric_list, row, agent_output)
        _log_llm_call(db, run.id, case.case_no, "全部指标", _prompt, res)
    except Exception:
        log.warning("log llm call failed for case %s", case.case_no, exc_info=True)

    # 组装标准指标结果（按权重排序，与 evaluator.metrics 顺序一致）
    std_metrics = []
    for sm in std_metric_list:
        matched = next((x for x in res["standard_metrics"] if x["metric_id"] == sm["id"]), None)
        std_metrics.append({
            "metricId": sm["id"], "name": sm["name"],
            "weight": sm["weight"],
            "score": matched["score"] if matched else 0.0,
            "reason": matched["reason"] if matched else "LLM 未返回该指标评分",
        })

    extra_metrics = []
    for em in extra_metric_list:
        matched = next((x for x in res["extra_metrics"] if x["metric_id"] == em["id"]), None)
        extra_metrics.append({
            "metricId": em["id"], "name": em["name"],
            "score": matched["score"] if matched else 0.0,
            "reason": matched["reason"] if matched else "LLM 未返回该指标评分",
        })

    brief_comment = res["brief_comment"]
    failure_attribution = res["failure_attribution"]
    total_tokens = res.get("usage", {}).get("total_tokens", 0)
    total_latency = res.get("latency_sec", 0)
    raw_llm = [
        {"metricId": sm["id"], "name": sm["name"], **next((x for x in res["standard_metrics"] if x["metric_id"] == sm["id"]), {})}
        for sm in std_metric_list
    ] + [
        {"metricId": em["id"], "name": em["name"], **next((x for x in res["extra_metrics"] if x["metric_id"] == em["id"]), {})}
        for em in extra_metric_list
    ]

    score_sec = round(time.monotonic() - _t_score, 2)
    _write_log(db, run.id, "info", f"用例 {case.case_no} 评分完成，耗时 {score_sec}s")

    # 2) 主分 = Σ(标准指标分 × weight)；通过 = 主分 >= 阈值（配置中心）
    overall = sum(m["score"] * m["weight"] for m in std_metrics)
    _pt_row = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    pass_threshold = float(_pt_row.config_value.get("value", settings.PASS_THRESHOLD)) if _pt_row else settings.PASS_THRESHOLD
    passed = overall >= pass_threshold
    cr.overall_score = round(overall, 3)
    cr.standard_metrics = std_metrics
    cr.extra_metrics = extra_metrics
    cr.brief_comment = brief_comment
    cr.token_usage = total_tokens
    cr.latency_sec = round(total_latency, 2)
    cr.raw_llm = raw_llm
    cr.failure_attribution = failure_attribution if not passed else None
    # 注意：agent_output/target_trace/node_id/trace_no 已在 _execute_case 落库，这里不动
    cr.status = "passed" if passed else "failed"
    cr.finished_at = _utcnow()
    _write_log(db, run.id, "success" if passed else "warn",
               f"用例 {case.case_no} {'通过' if passed else '未通过'}，主分 {cr.overall_score}")

    # 3) 同步 run 计数（实时 COUNT，避免重试重复计数）+ 累加评分耗时
    _sync_run_counters(db, run.id)
    db.execute(
        update(Run)
        .where(Run.id == run.id)
        .values(score_sec=func.coalesce(Run.score_sec, 0) + score_sec)
    )
    # 显式 flush：把 cr 的分数/状态脏数据先生成 SQL，与计数同事务原子提交，
    # 兜底防御 LLM 调用中途任何 commit/expire 冲掉这批未提交数据。
    db.flush()
    db.commit()
    return passed


def process_case(cr_id: str) -> None:
    """处理单条 case（非轮次模式，独立会话，崩溃不影响其他）。

    cr_id 是 case_result.id（claim_case 已把该行置 running + 记锁）。
    """
    db: Session = SessionLocal()
    lease_hb = None
    try:
        cr = db.get(CaseResult, uuid.UUID(cr_id))
        if cr is None:
            return
        # 注意：不加 with_for_update()。执行过程会调被测 Agent（慢、几秒~几十秒），
        # 若在事务开头 FOR UPDATE 锁 Run 行，会把 runs 表这一热点行锁住整个执行周期。
        # 多个执行 worker 并发处理同一 run 的不同 case 时，各自先锁自己的 case_result 行
        # 再争 Run 行锁，形成相反加锁顺序的 AB-BA 死锁；也阻塞 pause/stop 路由的 UPDATE Run。
        # run 在此只读 status + 后续执行只读字段；对 Run 的更新（_sync_run_counters 实时
        # COUNT 覆盖写、exec_sec/score_sec 用 DB 端 func.coalesce 原子累加）不依赖此行锁。
        # 状态一致性由 _try_complete_run（无中间态 case 才 done）+ recover_stale_running 兜底。
        run = db.get(Run, cr.run_id)
        if run is None:
            return
        # 防御：claim 到后 run 状态可能已变。
        # paused 可恢复 → 回 pending；stopped/error 是终态 → 置 skipped（否则永久卡 running）。
        if run.status in ("paused", "stopped", "error"):
            cr.status = "pending" if run.status == "paused" else "skipped"
            cr.locked_by = None
            cr.locked_at = None
            if cr.status == "skipped":
                _sync_run_counters(db, run.id)
            db.commit()
            return

        case = db.get(Case, cr.case_id)
        if case is None:
            cr.status = "error"
            _clear_result_fields(cr)
            cr.error_msg = "case not found"
            cr.finished_at = _utcnow()
            _sync_run_counters(db, run.id)
            db.commit()
            return

        row = {
            "case_id": str(case.id), "case_no": case.case_no, "user_input": case.user_input,
            "expected_gt": case.expected_gt,
            "dimension_l1": case.dimension_l1 or "", "dimension_l2": case.dimension_l2 or "",
        }
        r = get_redis()
        lease_hb = _LeaseHeartbeat(str(cr.locked_by or ""), [cr_id])
        lease_hb.start()
        target_trace: list = []
        result_extras: dict = {}
        effective_chain = None
        if getattr(run, "mode", "exec") != "eval_import":
            template = db.get(FlowTemplate, run.flow_template_id)
            if template is None:
                raise RuntimeError(
                    f"任务 {run.id} (mode={getattr(run, 'mode', 'exec')}) 缺少流程模板 "
                    f"flow_template_id={run.flow_template_id}，无法执行"
                )
            effective_chain = apply_overrides(template.chain_json, run.overrides)
            # 前置 API（与轮次解耦，v1.6）：有变量组时按 case.sort_order 循环取组、
            # 每组独立 session；无变量组时所有 case 共享一个 global session
            if pre_api_enabled(template.chain_json):
                group_vars = ensure_case_session(str(run.id), case.sort_order, template.chain_json, r, trace=target_trace)
                row.update(group_vars)

        # 执行（与评分解耦：成功 → cr.status='executed'，评分由评分池异步处理）。
        # 非阻塞让出：被测槽位忙（SlotBusy）→ 回 pending 让出 worker 线程，
        # 槽位空了队列重新调度，不原地 sleep 占线程（避免池子耗尽死锁）。
        # 真超时/网络错误（Agent 响应超时）→ 标 error（终态）。
        try:
            _execute_case(db, run, cr, case, row, r, target_trace, result_extras, effective_chain)
            _clear_yield_count(r, cr_id)  # 执行成功，清让出计数
        except SlotBusy as e:
            # 防活锁：让出计数超上限 → 标 error，否则回 pending 让出
            yc = _incr_yield_count(r, cr_id)
            if yc > YIELD_LIMIT_MAX:
                _write_log(db, run.id, "error", f"用例 {case.case_no} 被测槽位持续忙（让出{yc}次），标 error")
                cr.status = "error"
                _clear_result_fields(cr)
                cr.error_msg = f"被测 Agent 并发槽位持续繁忙，让出 {yc} 次后放弃"
                cr.finished_at = _utcnow()
                _sync_run_counters(db, run.id)
                db.commit()
                _clear_yield_count(r, cr_id)
                return
            _write_log(db, run.id, "info", f"用例 {case.case_no} 被测槽位忙，让出退避{YIELD_BACKOFF_SEC}s({yc}): {str(e)[:100]}")
            cr.status = "pending"
            cr.locked_by = None
            # 退避：locked_at 设为未来时间，claim 跳过，给占槽位的 case 时间完成
            cr.locked_at = _utcnow() + timedelta(seconds=YIELD_BACKOFF_SEC)
            db.commit()
            return  # worker 线程释放，去抢下一个 case
        except (TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            _write_log(db, run.id, "error", f"用例 {case.case_no} 执行超时: {str(e)[:200]}")
            cr.status = "error"
            _clear_result_fields(cr)
            cr.error_msg = str(e)[:500]
            cr.finished_at = _utcnow()
            _sync_run_counters(db, run.id)
            db.commit()
            _clear_yield_count(r, cr_id)

        # 完成检测：原子抢占 done 状态（评分结束才 done，见 _try_complete_run）
        if _try_complete_run(db, run.id):
            _trigger_report(db, db.get(Run, run.id))
        db.commit()
        # SSE 事件推送（执行完成事件；评分完成由 process_score 推）
        try:
            import json as _json
            latest_status = db.execute(select(Run.status).where(Run.id == run.id)).scalar()
            event = {
                "type": "case_executed" if latest_status != "done" else "run_done",
                "run_id": str(run.id),
                "case_result_id": cr_id,
                "case_status": cr.status,
                "run_status": latest_status,
            }
            get_redis().publish(f"agent_eval:events:{run.id}", _json.dumps(event))
        except Exception:
            log.warning("SSE publish failed for run %s", run.id, exc_info=True)
    except Exception as e:  # noqa: BLE001
        log.exception("case_result %s failed", cr_id)
        import traceback as _tb
        # 关键：_execute_case 内部 db.commit() 会 expire 掉 cr 等 ORM 对象，
        # 异常抛出后 cr 处于失效/脏状态。先 rollback 清状态，再重新加载干净的 cr。
        db.rollback()
        try:
            cr = db.get(CaseResult, uuid.UUID(cr_id))
            if cr is None:
                return
            # 兜底：执行阶段未捕获的异常（如模板缺失 RuntimeError）→ 标 error
            _write_log(db, cr.run_id, "error", f"用例执行出错: {str(e)[:200]}")
            cr.status = "error"
            _clear_result_fields(cr)
            cr.error_msg = str(e)[:500] + "\n" + _tb.format_exc()[-1500:]
            cr.finished_at = _utcnow()
            _sync_run_counters(db, cr.run_id)
            if _try_complete_run(db, cr.run_id, "（含异常用例）"):
                _trigger_report(db, db.get(Run, cr.run_id))
            db.commit()
        except Exception:
            log.exception("error handling for case_result %s failed", cr_id)
            db.rollback()
    finally:
        if lease_hb is not None:
            lease_hb.stop()
        db.close()


def process_round(round_info: dict) -> None:
    """处理一个轮次（整组 case 串行执行）。

    round_info = {"run_id": str, "round_no": int, "case_result_ids": [str, ...]}
    claim_round 已把该组所有 case 置 running + 记锁。
    """
    run_id = round_info["run_id"]
    round_no = round_info["round_no"]
    case_result_ids = round_info["case_result_ids"]

    db: Session = SessionLocal()
    lease_hb = None
    try:
        # 注意：不加 with_for_update()，理由同 process_case——轮次整组执行更久（组内多 case
        # 串行 + 调被测 Agent），FOR UPDATE 锁 Run 行会把热点行锁住整个轮次，多个执行 worker
        # 并发时形成 AB-BA 死锁。run 只读 status 判断防御，更新走原子 SQL，一致性命
        # _try_complete_run + recover_stale_running 兜底。
        run = db.get(Run, uuid.UUID(run_id))
        if run is None:
            return
        if run.status in ("paused", "stopped", "error"):
            # 回 pending，不执行
            for cr_id in case_result_ids:
                cr = db.get(CaseResult, uuid.UUID(cr_id))
                if cr:
                    cr.status = "pending"
                    cr.locked_by = None
                    cr.locked_at = None
            db.commit()
            return

        _write_log(db, run.id, "info", f"开始执行第 {round_no + 1}/{run.total_rounds} 轮（{len(case_result_ids)} 个用例）")
        db.commit()

        # 1. 加载模板
        r = get_redis()
        template = db.get(FlowTemplate, run.flow_template_id)
        if template is None and run.mode != "eval_import":
            raise RuntimeError(f"任务 {run.id} 缺少流程模板")

        # 2. 应用 overrides
        effective_chain = None
        if run.mode != "eval_import" and template:
            effective_chain = apply_overrides(template.chain_json, run.overrides)

        # 3. 组内 case 按 sort_order 串行执行
        # 加载所有 case，按 sort_order 排序
        cr_objs = []
        for cr_id in case_result_ids:
            cr = db.get(CaseResult, uuid.UUID(cr_id))
            if cr:
                cr_objs.append(cr)
        # 按 Case.sort_order 排序
        case_map = {cr.case_id: db.get(Case, cr.case_id) for cr in cr_objs}
        cr_objs.sort(key=lambda cr: case_map[cr.case_id].sort_order if case_map.get(cr.case_id) else 0)

        lease_hb = _LeaseHeartbeat(
            str(cr_objs[0].locked_by) if cr_objs else "",
            [str(cr.id) for cr in cr_objs],
        )
        lease_hb.start()

        for cr in cr_objs:
            case = case_map[cr.case_id]
            if case is None:
                cr.status = "error"
                _clear_result_fields(cr)
                cr.error_msg = "case not found"
                cr.finished_at = _utcnow()
                _sync_run_counters(db, run.id)
                db.commit()
                continue

            # 每个 case 执行前检查 session 是否有效（快过期自动刷新）
            # trace 传入 target_trace：session 刷新时前置 API 的调用记录也会进入该 case 的 API 调用过程
            target_trace: list = []
            result_extras: dict = {}
            group_vars = ensure_session(str(run.id), round_no, template.chain_json, r, trace=target_trace)

            # 合并组级变量到 row
            row = {
                "case_id": str(case.id), "case_no": case.case_no, "user_input": case.user_input,
                "expected_gt": case.expected_gt,
                "dimension_l1": case.dimension_l1 or "", "dimension_l2": case.dimension_l2 or "",
                **group_vars,  # session_id 等
            }

            # 执行（与评分解耦：成功 → cr.status='executed'，评分由评分池异步处理）。
            # 非阻塞让出：被测槽位忙（SlotBusy）→ 整组回 pending 让出 worker 线程，
            # 槽位空了 claim_round 重新整组抢（保组内顺序），不原地 sleep 占线程。
            # 真超时/网络错误 → 标 error，后续 case 继续（弱依赖）。
            try:
                _execute_case(db, run, cr, case, row, r, target_trace, result_extras, effective_chain)
                _clear_yield_count(r, str(cr.id))  # 执行成功，清让出计数
            except SlotBusy as e:
                # 防活锁：让出计数超上限 → 当前 case 标 error，后续 case 继续（弱依赖）
                yc = _incr_yield_count(r, str(cr.id))
                if yc > YIELD_LIMIT_MAX:
                    _write_log(db, run.id, "error", f"第 {round_no + 1} 轮用例 {case.case_no} 被测槽位持续忙（让出{yc}次），标 error")
                    cr.status = "error"
                    _clear_result_fields(cr)
                    cr.error_msg = f"被测 Agent 并发槽位持续繁忙，让出 {yc} 次后放弃"
                    cr.finished_at = _utcnow()
                    _sync_run_counters(db, run.id)
                    db.commit()
                    _clear_yield_count(r, str(cr.id))
                    continue  # 弱依赖：后续 case 继续
                # 整组让出：当前 case + 后续未执行 case 全部回 pending，
                # worker 线程释放，槽位空了 claim_round 重新整组调度（保序）。
                # 退避：locked_at 设为未来时间，YIELD_BACKOFF_SEC 内不被重抢。
                _write_log(db, run.id, "info", f"第 {round_no + 1} 轮用例 {case.case_no} 被测槽位忙，整组让出退避{YIELD_BACKOFF_SEC}s({yc}): {str(e)[:100]}")
                backoff_until = _utcnow() + timedelta(seconds=YIELD_BACKOFF_SEC)
                for cr2 in cr_objs:
                    if cr2.status in ("running", "pending"):
                        cr2.status = "pending"
                        cr2.locked_by = None
                        cr2.locked_at = backoff_until
                db.commit()
                return  # worker 线程释放
            except (TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
                _write_log(db, run.id, "error", f"用例 {case.case_no} 执行超时: {str(e)[:200]}")
                cr.status = "error"
                _clear_result_fields(cr)
                cr.error_msg = str(e)[:500]
                cr.finished_at = _utcnow()
                _sync_run_counters(db, run.id)
                db.commit()
                continue  # 弱依赖：后续 case 继续

        # 4. 轮次完成，递增 done_rounds
        db.execute(
            update(Run)
            .where(Run.id == run.id)
            .values(done_rounds=Run.done_rounds + 1)
        )
        _write_log(db, run.id, "info", f"第 {round_no + 1}/{run.total_rounds} 轮完成")

        # 5. 完成检测：done_rounds >= total_rounds，原子抢占 done 状态
        latest = db.execute(
            select(Run.done_rounds, Run.total_rounds).where(Run.id == run.id)
        ).one()
        if latest[0] >= latest[1]:
            if _try_complete_run(db, run.id):
                _trigger_report(db, db.get(Run, run.id))
        db.commit()

        # 6. SSE 事件推送
        try:
            import json as _json
            latest_status = db.execute(select(Run.status).where(Run.id == run.id)).scalar()
            event = {
                "type": "round_done" if latest_status != "done" else "run_done",
                "run_id": str(run.id),
                "round_no": round_no,
                "run_status": latest_status,
            }
            get_redis().publish(f"agent_eval:events:{run.id}", _json.dumps(event))
        except Exception:
            log.warning("SSE publish failed for run %s", run.id, exc_info=True)
    except Exception as e:  # noqa: BLE001
        log.exception("round %d of run %s failed", round_no, run_id)
        import traceback as _tb
        # 同 process_case：for 循环内每个 case 都 db.commit()，异常抛出后 run/cr
        # 等 ORM 对象已失效。先 rollback 再重新加载，避免 commit 时 PendingRollbackError
        # 被吞导致整组 case 卡 running、run 永不完成。
        db.rollback()
        try:
            run = db.get(Run, uuid.UUID(run_id))
            if run is None:
                return
            _write_log(db, run.id, "error", f"轮次 {round_no + 1} 执行出错: {str(e)[:200]}")
            # 整组标记 error
            for cr_id in case_result_ids:
                cr = db.get(CaseResult, uuid.UUID(cr_id))
                if cr and cr.status == "running":
                    cr.status = "error"
                    _clear_result_fields(cr)
                    cr.error_msg = str(e)[:500] + "\n" + _tb.format_exc()[-1500:]
                    cr.finished_at = _utcnow()
            _sync_run_counters(db, run.id)
            db.execute(
                update(Run)
                .where(Run.id == run.id)
                .values(done_rounds=Run.done_rounds + 1)
            )
            latest = db.execute(
                select(Run.done_rounds, Run.total_rounds).where(Run.id == run.id)
            ).one()
            if latest[0] >= latest[1]:
                if _try_complete_run(db, run.id, "（含异常轮次）"):
                    _trigger_report(db, db.get(Run, run.id))
            db.commit()
        except Exception:
            db.rollback()
    finally:
        if lease_hb is not None:
            lease_hb.stop()
        db.close()


def process_score(cr_id: str) -> None:
    """评分单条 case（评分池专用，与执行解耦、不依赖组顺序）。

    cr_id 是 case_result.id（claim_score_task 已把该行置 scoring + 记锁）。
    读已落库的 agent_output → 调 LLM 评分 → 算主分 → 落库 → 置 passed/failed。
    评分不依赖组：可并发（受 model_concurrency 限流），乱序完成不影响正确性。
    """
    db: Session = SessionLocal()
    lease_hb = None
    try:
        cr = db.get(CaseResult, uuid.UUID(cr_id))
        if cr is None:
            return
        # 注意：这里不加 with_for_update()。评分过程会多次调 LLM（慢、几秒~几十秒），
        # 若在事务开头就 FOR UPDATE 锁 Run 行，会把 runs 表这一热点行锁住整个评分周期，
        # 与执行 worker（process_case/process_round 也 FOR UPDATE 锁 Run 行 + UPDATE 计数）
        # 形成相反加锁顺序的 AB-BA 死锁（报错 "psycopg2 DeadlockDetected"）。
        # run 在此只读 status + evaluator_id/extra_metric_ids/model_concurrency 等
        # 评分过程中不被修改的字段；后续对 Run 的更新（_sync_run_counters 实时 COUNT
        # 覆盖写、score_sec 用 DB 端 func.coalesce 原子累加）均不依赖事务开头的行锁。
        run = db.get(Run, cr.run_id)
        if run is None:
            return
        # 防御：claim 到后 run 状态可能已变。
        # paused 可恢复 → 回 executed（待评分）；stopped/error 是终态 → 置 skipped。
        if run.status in ("paused", "stopped", "error"):
            cr.status = "executed" if run.status == "paused" else "skipped"
            cr.locked_by = None
            cr.locked_at = None
            if cr.status == "skipped":
                cr.finished_at = _utcnow()
                _sync_run_counters(db, run.id)
            db.commit()
            return

        case = db.get(Case, cr.case_id)
        if case is None:
            cr.status = "error"
            _clear_result_fields(cr)
            cr.error_msg = "case not found"
            cr.finished_at = _utcnow()
            _sync_run_counters(db, run.id)
            db.commit()
            return

        row = {
            "case_id": str(case.id), "case_no": case.case_no, "user_input": case.user_input,
            "expected_gt": case.expected_gt,
            "dimension_l1": case.dimension_l1 or "", "dimension_l2": case.dimension_l2 or "",
        }
        r = get_redis()
        lease_hb = _LeaseHeartbeat(str(cr.locked_by or ""), [cr_id])
        lease_hb.start()

        try:
            _score_case(db, run, cr, case, row, r)
            _clear_yield_count(r, cr_id)  # 评分成功，清让出计数
        except SlotBusy as e:
            # 防活锁：让出计数超上限 → 标 error，否则回 executed 让出
            yc = _incr_yield_count(r, cr_id)
            if yc > YIELD_LIMIT_MAX:
                _write_log(db, run.id, "error", f"用例 {case.case_no} LLM 槽位持续忙（让出{yc}次），标 error")
                cr.status = "error"
                cr.error_msg = f"LLM 并发槽位持续繁忙，让出 {yc} 次后放弃"
                cr.finished_at = _utcnow()
                _sync_run_counters(db, run.id)
                db.commit()
                _clear_yield_count(r, cr_id)
                return
            _write_log(db, run.id, "info", f"用例 {case.case_no} LLM 槽位忙，让出退避{YIELD_BACKOFF_SEC}s({yc}): {str(e)[:100]}")
            cr.status = "executed"
            cr.locked_by = None
            cr.locked_at = _utcnow() + timedelta(seconds=YIELD_BACKOFF_SEC)  # 退避
            db.commit()
            return  # worker 线程释放

        # 完成检测：评分结束才 done（_try_complete_run 检查无中间态 case）
        if _try_complete_run(db, run.id):
            _trigger_report(db, db.get(Run, run.id))
        db.commit()
        # SSE 事件推送（评分完成）
        try:
            import json as _json
            latest_status = db.execute(select(Run.status).where(Run.id == run.id)).scalar()
            event = {
                "type": "case_scored" if latest_status != "done" else "run_done",
                "run_id": str(run.id),
                "case_result_id": cr_id,
                "case_status": cr.status,
                "overall_score": float(cr.overall_score) if cr.overall_score is not None else None,
                "run_status": latest_status,
            }
            get_redis().publish(f"agent_eval:events:{run.id}", _json.dumps(event))
        except Exception:
            log.warning("SSE publish failed for run %s", run.id, exc_info=True)
    except Exception as e:  # noqa: BLE001
        log.exception("score case_result %s failed", cr_id)
        import traceback as _tb
        # 同 process_case：_score_case 内部 db.commit() 会 expire ORM 对象，
        # 先 rollback 再重新加载干净的 cr。
        db.rollback()
        try:
            cr = db.get(CaseResult, uuid.UUID(cr_id))
            if cr is None:
                return
            # 评分瞬时错误（LLM 超时）回 executed 让评分池重试；
            # 不可恢复错误标 error。最多重试 2 次（attempt 从执行阶段累加）。
            retryable = (
                cr.attempt < 3
                and isinstance(e, (TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError))
            )
            if retryable:
                _write_log(db, cr.run_id, "warn", f"用例评分瞬时错误，回退重试: {str(e)[:200]}")
                cr.status = "executed"
                cr.locked_by = None
                cr.locked_at = None
                db.commit()
                return
            _write_log(db, cr.run_id, "error", f"用例评分出错: {str(e)[:200]}")
            cr.status = "error"
            cr.error_msg = str(e)[:500] + "\n" + _tb.format_exc()[-1500:]
            cr.finished_at = _utcnow()
            _sync_run_counters(db, cr.run_id)
            if _try_complete_run(db, cr.run_id, "（含评分异常用例）"):
                _trigger_report(db, db.get(Run, cr.run_id))
            db.commit()
        except Exception:
            log.exception("error handling for score case_result %s failed", cr_id)
            db.rollback()
    finally:
        if lease_hb is not None:
            lease_hb.stop()
        db.close()


def _trigger_report(db: Session, run: Run) -> None:
    """run 完成后代码聚合报告（跨模块调用 reports 模块）。"""
    from ..reports.report_service import build_report
    try:
        build_report(db, run)
    except Exception:
        log.exception("report build failed for run %s", run.id)


def _try_complete_run(db: Session, run_id, log_suffix: str = "") -> bool:
    """原子抢占 run 完成状态：只有第一个把 status 从 running 改为 done 的 worker 返回 True。

    避免多 worker 同时完成最后几条 case 时重复触发报告。
    返回 True 表示本 worker 抢到了完成权，调用方应触发报告 + SSE。

    执行与评分解耦后，完成判定 = "无中间态 case"（pending/running/executed/scoring 全清空）。
    即所有 case 都到达终态（passed/failed/error/skipped）才 done，评分结束才完成。
    """
    # 先检查是否还有中间态 case；有则未完成，直接返回 False（不改状态）
    intermediate = db.execute(
        select(func.count(CaseResult.id))
        .where(CaseResult.run_id == run_id, CaseResult.status.in_(_INTERMEDIATE_STATUSES))
    ).scalar()
    if intermediate and intermediate > 0:
        return False

    avg = db.execute(
        select(func.avg(CaseResult.overall_score))
        .where(CaseResult.run_id == run_id, CaseResult.overall_score.isnot(None))
    ).scalar()
    result = db.execute(
        update(Run)
        .where(Run.id == run_id, Run.status == "running")
        .values(
            status="done",
            finished_at=_utcnow(),
            overall_score=round(float(avg), 3) if avg is not None else None,
        )
    )
    if result.rowcount == 0:
        return False  # 已被其他 worker 完成
    total = db.execute(select(Run.total_cases).where(Run.id == run_id)).scalar()
    done = db.execute(select(Run.done_cases).where(Run.id == run_id)).scalar()
    _write_log(db, run_id, "success",
               f"任务执行完成{log_suffix}：{done}/{total} 用例，平均分 {round(float(avg), 3) if avg is not None else 'N/A'}")
    return True


def _recovery_loop() -> None:
    """周期性回收卡死的 running/error case（locked_at 超时且无 finished_at → 回 pending）。

    兜底：即使异常处理路径仍有遗漏导致 case 卡 running，也能自动回收，
    避免 run 永久停在 running（"任务卡死在执行中"需人工重启才能恢复）。
    """
    while not _stop_flag.is_set():
        _stop_flag.wait(settings.STALE_RUNNING_RECOVER_INTERVAL_SEC)
        if _stop_flag.is_set():
            break
        try:
            recovered = task_queue.recover_stale_running(settings.STALE_RUNNING_MAX_AGE_SEC)
            if recovered:
                log.warning("periodic recovery: recovered %d stale case_results", recovered)
        except Exception:
            log.exception("periodic stale recovery failed")


def start_workers() -> None:
    """启动执行池 + 评分池 + 回收线程（单副本内并发；多副本靠多容器）。

    - 执行池（WORKER_COUNT 线程）：抢 pending case / 整组轮次 → 调被测 Agent → 置 executed
    - 评分池（CONCURRENCY_MODEL 线程）：抢 executed case → 调 LLM 评分 → 置 passed/failed
      评分线程数 = LLM 并发上限（model_concurrency），保证线程数 ≤ 槽位数，
      避免结构性 SlotBusy（线程数 > 槽位数时，多指标 case 必然抢不到槽位让出）。
    - 回收线程：周期性回收卡死的 running/scoring case（兜底）

    执行与评分解耦：两池独立，互不阻塞。
    启动时先回收崩溃遗留的 running/scoring case，再起线程。
    注意：model_concurrency 来自全局配置 concurrency.model，改配置后需重启服务生效。
    """
    recovered = task_queue.recover_stale_running(settings.STALE_RUNNING_MAX_AGE_SEC)
    if recovered:
        log.info("recovered %d stale case_results", recovered)
    for i in range(settings.WORKER_COUNT):
        worker_id = f"exec-{i}"
        t = threading.Thread(target=_worker_loop, args=(worker_id,), name=worker_id, daemon=True)
        t.start()
    for i in range(settings.CONCURRENCY_MODEL):
        worker_id = f"score-{i}"
        t = threading.Thread(target=_score_worker_loop, args=(worker_id,), name=worker_id, daemon=True)
        t.start()
    rec = threading.Thread(target=_recovery_loop, name="stale-recovery", daemon=True)
    rec.start()
    log.info("started %d exec workers + %d score workers + stale-recovery",
             settings.WORKER_COUNT, settings.CONCURRENCY_MODEL)


def _worker_loop(worker_id: str) -> None:
    while not _stop_flag.is_set():
        # 判断是轮次模式还是非轮次模式
        # 轮次模式：run.round_size 非空
        # 非轮次模式：run.round_size 为空
        # 这里先尝试 claim_round，如果返回 None 再尝试 claim_case
        round_info = task_queue.claim_round(worker_id)
        if round_info is not None:
            try:
                process_round(round_info)
            except Exception:
                log.exception("worker loop error (round)")
            continue

        cr_id = task_queue.claim_case(worker_id)
        if cr_id is None:
            time.sleep(settings.WORKER_CLAIM_POLL_SEC)
            continue
        try:
            process_case(cr_id)
        except Exception:
            log.exception("worker loop error")


def _score_worker_loop(worker_id: str) -> None:
    """评分 worker 循环：抢 executed case → 评分。

    与执行池独立，不抢执行任务。评分不依赖组顺序，纯按 status='executed' 抢。
    """
    while not _stop_flag.is_set():
        cr_id = task_queue.claim_score_task(worker_id)
        if cr_id is None:
            time.sleep(settings.WORKER_CLAIM_POLL_SEC)
            continue
        try:
            process_score(cr_id)
        except Exception:
            log.exception("score worker loop error")


def stop_workers() -> None:
    _stop_flag.set()

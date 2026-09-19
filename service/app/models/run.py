import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Run(Base):
    """一次评测执行任务。状态机支持 暂停/继续/停止 + 断点续跑。"""
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    evaluator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    flow_template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # eval_import 任务无模板
    # 任务类型：exec=执行任务（调被测 Agent）/ eval_import=评测结果打分任务（agent_output 导入时已填，跳过调被测）
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="exec")
    extra_metric_ids: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    # 用户可编辑参数覆盖：{paramPath: value}，执行前应用到 chain_json（P13）
    overrides: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    # pending|running|paused|done|error|stopped
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overall_score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    model_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    target_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # 轮次（exec 模式）：每组用例数 / 总轮次数 / 已完成轮次数
    round_size: Mapped[int | None] = mapped_column(Integer)
    total_rounds: Mapped[int | None] = mapped_column(Integer)
    done_rounds: Mapped[int | None] = mapped_column(Integer, default=0)
    # 任务级耗时累计（worker 逐 case 累加）：exec=调被测 Agent，score=调 LLM 打分
    exec_sec: Mapped[float | None] = mapped_column(Numeric(10, 2))
    score_sec: Mapped[float | None] = mapped_column(Numeric(10, 2))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    case_results: Mapped[list["CaseResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class CaseResult(Base):
    """逐用例结果（断点续跑依据：取 status IN pending/running 续跑）。"""
    __tablename__ = "case_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    # pending|running|passed|failed|error|skipped
    overall_score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    standard_metrics: Mapped[list | None] = mapped_column(JSONB)  # [{metricId,name,weight,score,reason}]
    extra_metrics: Mapped[list | None] = mapped_column(JSONB)     # [{metricId,name,score,reason}]
    brief_comment: Mapped[str | None] = mapped_column(Text)       # P18: LLM 顺带输出的一句话问题说明
    agent_output: Mapped[str | None] = mapped_column(Text)
    token_usage: Mapped[int | None] = mapped_column(Integer)
    latency_sec: Mapped[float | None] = mapped_column(Numeric(8, 2))
    error_msg: Mapped[str | None] = mapped_column(Text)
    raw_llm: Mapped[dict | None] = mapped_column(JSONB)
    failure_attribution: Mapped[dict | None] = mapped_column(JSONB)  # 失败归因（仅 failed 用例）
    target_trace: Mapped[list | None] = mapped_column(JSONB)  # 被测 Agent 逐步请求/响应轨迹（定位用）
    # 流程模板步骤 extract_to_result 回写的执行关联凭证（node_id/trace_no 等）
    node_id: Mapped[str | None] = mapped_column(Text)
    trace_no: Mapped[str | None] = mapped_column(String(128))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 执行重试次数（含槽位让出）
    score_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 评分重试次数（独立于执行）
    # 执行阶段时间戳（调被测 Agent 的起止时刻；评分阶段另有 finished_at 记录终态时刻）
    exec_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exec_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # PG 队列：抢任务辅助列（locked_by 记录 worker 标识，locked_at 用于崩溃回收）
    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    run: Mapped["Run"] = relationship(back_populates="case_results")


class RunLog(Base):
    """任务执行日志（terminal 风格展示）。"""
    __tablename__ = "run_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    # info | success | error | warn
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

"""任务（run）/ 逐用例结果 / 看板相关请求响应模型。"""
from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator
from typing import Optional

from ..shared import _uuid_to_str


class RunCreateReq(BaseModel):
    task_name: str
    dataset_id: str
    flow_template_id: str
    extra_metric_ids: list[str] = []
    overrides: dict = {}  # 仅允许 user_editable 参数
    round_size: int | None = None  # 每组用例数（exec 模式必填，eval_import 忽略）


class EvalImportColumnMapping(BaseModel):
    """评测结果打分导入的列映射（比数据集多 agent_output 必填列）。"""
    case_no: str
    user_input: str
    expected_gt: str
    agent_output: str
    dimension_l1: str | None = None
    dimension_l2: str | None = None


class RunOut(BaseModel):
    id: str
    task_name: str
    owner_id: str
    username: str | None = None
    dataset_id: str
    flow_template_id: str | None = None
    mode: str = "exec"  # exec / eval_import
    status: str
    total_cases: int
    done_cases: int
    passed_cases: int
    failed_cases: int
    overall_score: float | None
    model_concurrency: int
    target_concurrency: int
    round_size: int | None = None
    total_rounds: int | None = None
    done_rounds: int | None = None
    exec_sec: float | None = None
    score_sec: float | None = None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    score_status: str = "pending"  # scored|pending，由 status 派生
    report_id: str | None = None  # 关联报告 ID（任务完成后生成）

    @field_validator("id", "owner_id", "dataset_id", "flow_template_id", mode="before")
    @classmethod
    def _ids(cls, v):
        return _uuid_to_str(cls, v)

    @model_validator(mode="after")
    def _derive_score_status(self):
        # 任务 done 即视为已打分；其余状态（pending/running/paused/error/stopped）待打分。
        # 用 model_validator(after) 而非 field_validator：后者在字段构造期触发，
        # 此时 status 字段（定义在 score_status 之后）尚未填入 info.data，会恒为 pending。
        self.score_status = "scored" if self.status == "done" else "pending"
        return self

    class Config:
        from_attributes = True


class CaseResultOut(BaseModel):
    id: str
    case_id: str
    case_no: Optional[str] = None
    status: str
    overall_score: float | None
    standard_metrics: list | None
    extra_metrics: list | None
    brief_comment: str | None
    failure_attribution: dict | None = None
    agent_output: str | None
    token_usage: int | None
    latency_sec: float | None
    error_msg: str | None
    target_trace: list | None = None  # 被测 Agent 逐步请求/响应轨迹
    node_id: str | None = None        # 流程模板 extract_to_result 回写的执行关联凭证
    trace_no: str | None = None
    exec_started_at: datetime | None = None   # 执行开始时刻（调被测 Agent 前）
    exec_finished_at: datetime | None = None  # 执行结束时刻（被测 Agent 调用完成）

    @field_validator("id", "case_id", mode="before")
    @classmethod
    def _ids(cls, v):
        return _uuid_to_str(cls, v)

    class Config:
        from_attributes = True


class DashboardSummary(BaseModel):
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    total_runs: int
    running_runs: int
    token_usage: int
    avg_latency_sec: float

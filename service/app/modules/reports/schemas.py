"""报告相关请求响应模型。"""
from datetime import datetime

from pydantic import BaseModel, field_validator

from ..shared import _uuid_to_str


class ReportOut(BaseModel):
    id: str
    run_id: str
    task_name: str
    owner_id: str
    username: str | None = None
    summary: dict
    standard_metric_averages: list | None
    extra_metric_averages: list | None
    dimension_summary: list | None
    case_details: list | None
    failure_root_causes: list | None = None
    created_at: datetime

    @field_validator("id", "run_id", "owner_id", mode="before")
    @classmethod
    def _ids(cls, v):
        return _uuid_to_str(cls, v)

    class Config:
        from_attributes = True


class ReportCompareOut(BaseModel):
    """两份报告对比：指标均分/通过率/用例明细差异。"""
    a: dict  # {id, task_name, summary, standard_metric_averages}
    b: dict
    metric_diff: list  # [{name, a_score, b_score, delta}]
    case_diff: list    # [{case_no, a_status, b_status, a_score, b_score}]

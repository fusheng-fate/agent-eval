"""标准评估器相关请求响应模型。"""
from pydantic import BaseModel, Field, field_validator

from ..shared import _uuid_to_str


class EvaluatorMetricIn(BaseModel):
    metric_id: str
    weight: float = Field(ge=0, le=1)


class StandardEvaluatorOut(BaseModel):
    id: str
    name: str
    description: str | None
    metrics: list[dict]  # [{metricId,name,category,industry,description,weight}]

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _uuid_to_str(cls, v)


class StandardEvaluatorUpdateReq(BaseModel):
    description: str | None = None
    metrics: list[EvaluatorMetricIn]

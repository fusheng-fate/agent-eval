"""指标库相关请求响应模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from ..shared import _uuid_to_str


class MetricOut(BaseModel):
    id: str
    name: str
    category: str
    industry: str | None
    description: str | None
    skill_md: str
    is_builtin: bool
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _uuid_to_str(cls, v)

    class Config:
        from_attributes = True


class MetricCreateReq(BaseModel):
    name: str
    category: Literal["tech", "biz"] = "tech"
    industry: str | None = None
    description: str | None = None
    skill_md: str


class MetricUpdateReq(BaseModel):
    name: str | None = None
    category: Literal["tech", "biz"] | None = None
    industry: str | None = None
    description: str | None = None
    skill_md: str | None = None


class MetricListOut(BaseModel):
    items: list[MetricOut]
    page: int
    page_size: int
    total: int

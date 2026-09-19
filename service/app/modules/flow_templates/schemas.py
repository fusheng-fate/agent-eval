"""测试执行流程模板相关请求响应模型。"""
from datetime import datetime

from pydantic import BaseModel, field_validator

from ...core.config import settings
from ..shared import _uuid_to_str


class FlowTemplateOut(BaseModel):
    id: str
    name: str
    description: str | None
    chain_json: dict
    target_concurrency: int
    param_perms: list[dict]  # [{paramPath, userEditable}]
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _uuid_to_str(cls, v)


class FlowTemplateCreateReq(BaseModel):
    name: str
    description: str | None = None
    chain_json: dict
    target_concurrency: int = settings.CONCURRENCY_TARGET
    param_perms: list[dict] = []  # [{paramPath, userEditable}]

"""配置中心相关请求响应模型。"""
from typing import Any

from pydantic import BaseModel


class ConfigOut(BaseModel):
    config_key: str
    config_value: Any
    scope: str
    editable_by: str
    description: str | None


class ConfigBatchUpdateReq(BaseModel):
    values: dict[str, Any]

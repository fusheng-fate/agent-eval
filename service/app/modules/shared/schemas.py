"""通用响应模型（跨模块共享）。"""
import uuid as _uuid
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, field_validator

T = TypeVar("T")


class Msg(BaseModel):
    message: str
    ok: bool = True


class ApiResp(BaseModel, Generic[T]):
    """契约统一包裹结构 {code, message, data}。"""
    code: int = 0
    message: str = "ok"
    data: T | None = None


def ok(data: Any = None) -> dict:
    """成功响应：code=0，message=ok。"""
    return {"code": 0, "message": "ok", "data": data}


def fail(code: int, message: str) -> dict:
    """业务失败响应（HTTP 200 + 非 0 code）。"""
    return {"code": code, "message": message, "data": None}


class PageData(BaseModel, Generic[T]):
    """分页响应结构 {items, page, page_size, total}。"""
    items: list[T]
    page: int
    page_size: int
    total: int


def _uuid_to_str(cls, v):
    """把 ORM 的 UUID 对象统一转成 str（Pydantic v2 不会自动转 UUID→str）。

    作为 field_validator(mode="before") 挂到各 Out 模型的 id 字段上。
    """
    return str(v) if isinstance(v, _uuid.UUID) else v

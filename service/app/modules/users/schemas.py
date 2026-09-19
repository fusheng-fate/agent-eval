"""用户管理相关请求响应模型。"""
from datetime import datetime

from pydantic import BaseModel, field_validator

from ..shared import _uuid_to_str


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _uuid_to_str(cls, v)

    class Config:
        from_attributes = True


class CreateUserReq(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class ChangePasswordReq(BaseModel):
    password: str


class UserListOut(BaseModel):
    items: list[UserOut]
    page: int
    page_size: int
    total: int

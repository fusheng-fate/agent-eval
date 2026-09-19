"""认证 / 当前用户相关请求响应模型。"""
from datetime import datetime

from pydantic import BaseModel, field_validator

from ..shared import _uuid_to_str


class LoginReq(BaseModel):
    username: str
    password: str


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


class TokenResp(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class RefreshReq(BaseModel):
    refresh_token: str


class ChangePasswordReq(BaseModel):
    password: str


class RefreshResp(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

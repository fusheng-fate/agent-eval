"""FastAPI 依赖：当前用户 / 管理员校验 / owner-or-admin 校验。"""
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .security import decode_access_token, is_jti_blacklisted
from ..models import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = decode_access_token(cred.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    if is_jti_blacklisted(payload.get("jti", "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌已登出")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已停用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def require_owner_or_admin(resource_owner_id: uuid.UUID, user: User = Depends(get_current_user)) -> User:
    """普通用户只能操作自己的资源；管理员可操作所有。"""
    if user.role == "admin":
        return user
    if resource_owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权操作他人资源")
    return user

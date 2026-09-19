"""认证：登录 / 刷新 / 登出 / 当前用户 / 改自己密码。"""
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.deps import bearer, get_current_user
from ...core.security import (
    blacklist_jti,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from ...models import User
from ..shared import fail, ok
from .schemas import ChangePasswordReq, LoginReq, RefreshReq, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user: User) -> dict:
    access_token, access_exp = create_access_token(str(user.id), user.username, user.role)
    refresh_token, _ = create_refresh_token(str(user.id), user.username, user.role)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": max(int(access_exp) - int(time.time()), 0),
    }


@router.post("/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")
    data = _issue_tokens(user)
    data["user"] = UserOut.model_validate(user).model_dump()
    return ok(data)


@router.post("/refresh")
def refresh(req: RefreshReq, db: Session = Depends(get_db)):
    payload = decode_refresh_token(req.refresh_token)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效或已过期")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已停用")
    return ok(_issue_tokens(user))


@router.post("/logout")
def logout(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if cred is not None:
        payload = decode_access_token(cred.credentials)
        if payload is not None:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti is not None:
                exp_ts = int(exp.timestamp()) if isinstance(exp, datetime) else int(exp)
                blacklist_jti(jti, exp_ts)
    return ok()


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user).model_dump())


@router.post("/me/password")
def change_my_password(req: ChangePasswordReq, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.password_hash = hash_password(req.password)
    db.commit()
    return ok()

"""用户管理（仅管理员）：列表 / 注册 / 改密 / 停用（P23）。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.deps import require_admin
from ...core.security import hash_password
from ...models import User
from ..shared import fail, ok
from .schemas import ChangePasswordReq, CreateUserReq, UserListOut, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20
    q = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(User.username.ilike(like) | User.display_name.ilike(like))
    total = q.count()
    items = q.order_by(User.created_at).offset((page - 1) * page_size).limit(page_size).all()
    data = UserListOut(items=items, page=page, page_size=page_size, total=total)
    return ok(data.model_dump())


@router.post("")
def create_user(req: CreateUserReq, response: Response, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == req.username).first():
        return fail(40902, "用户名已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        display_name=req.display_name or req.username,
        role="tester",  # 管理员注册的都是普通用户
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    response.status_code = status.HTTP_201_CREATED
    return ok(UserOut.model_validate(user).model_dump())


@router.post("/{user_id}/password")
def change_password(user_id: uuid.UUID, req: ChangePasswordReq, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    user.password_hash = hash_password(req.password)
    db.commit()
    return ok()


@router.post("/{user_id}/deactivate")
def deactivate(user_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用自己")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.username == admin.username and user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用初始管理员")
    user.is_active = False
    db.commit()
    return ok()

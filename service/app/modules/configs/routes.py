"""配置中心：列表 / 读 / 改（按 editable_by 权限，P16/P21）。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.deps import get_current_user
from ...models import Config, User, UserConfig
from ..shared import ok
from .schemas import ConfigBatchUpdateReq, ConfigOut

router = APIRouter(prefix="/configs", tags=["configs"])

def _effective_value(db: Session, key: str, user: User):
    row = db.query(Config).filter(Config.config_key == key).first()
    if row is None:
        return None
    # personal 覆盖优先
    if row.scope == "personal":
        uc = db.query(UserConfig).filter(UserConfig.user_id == user.id, UserConfig.config_key == key).first()
        if uc:
            return uc.config_value
    return row.config_value


@router.get("")
def list_configs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = []
    for c in db.query(Config).order_by(Config.config_key).all():
        editable = c.editable_by == "admin" and user.role == "admin"
        out.append(ConfigOut(
            config_key=c.config_key,
            config_value=_effective_value(db, c.config_key, user),
            scope=c.scope, editable_by=c.editable_by, description=c.description,
        ))
    return ok([c.model_dump() for c in out])


@router.get("/{key}")
def get_config(key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.query(Config).filter(Config.config_key == key).first()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "配置不存在")
    return ok(ConfigOut(
        config_key=c.config_key, config_value=_effective_value(db, key, user),
        scope=c.scope, editable_by=c.editable_by, description=c.description,
    ).model_dump())


def _apply_update(db: Session, key: str, raw_value, user: User) -> bool:
    """更新单个配置，返回是否实际改动。

    - 配置不存在 → 跳过（返回 False，不报错）。
    - admin → 改全局 `configs.config_value`（无论 scope）。
    - 普通用户 → 仅当该 key 为个人级（scope=personal）时写 `user_configs` 覆盖；
      否则 403。即：普通用户即使传了全局 key，也只处理个人级、无权改全局。
    """
    c = db.query(Config).filter(Config.config_key == key).first()
    if c is None:
        return False
    # 数字字符串 → 数值类型（前端可能传 "6" 而非 6）
    if isinstance(raw_value, str) and raw_value.lstrip("-").isdigit():
        raw_value = int(raw_value) if "." not in raw_value else float(raw_value)
    value = raw_value if isinstance(raw_value, dict) else {"value": raw_value}
    if user.role == "admin":
        c.config_value = value
        c.updated_by = user.id
        return True
    # 普通用户：只处理个人级
    if c.scope == "personal":
        uc = db.query(UserConfig).filter(UserConfig.user_id == user.id, UserConfig.config_key == key).first()
        if uc:
            uc.config_value = value
        else:
            db.add(UserConfig(user_id=user.id, config_key=key, config_value=value))
        return True
    raise HTTPException(status.HTTP_403_FORBIDDEN, f"无权修改该配置: {key}")


@router.post("/batch-update")
def batch_update(req: ConfigBatchUpdateReq, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """批量更新配置：先查所有 config，存在则改、不存在则跳过。

    请求体：`{"values": {"key": <value>, ...}}`（value 可为任意 JSON）。
    权限按 scope 区分：admin 改全局；普通用户仅处理个人级（scope=personal），
    传了全局 key 也只改个人级、无权改全局（无权则 403）。
    """
    if not req.values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "values 不能为空")
    updated, skipped = [], []
    for key, value in req.values.items():
        if _apply_update(db, key, value, user):
            updated.append(key)
        else:
            skipped.append(key)
    db.commit()
    return ok({"updated": updated, "skipped": skipped})

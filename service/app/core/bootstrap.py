"""启动引导：建表 + 内置初始管理员 + 内置标准评估器。

幂等：重复启动不报错。
"""
import logging

from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine
from .security import hash_password
from ..models import Evaluator, User

log = logging.getLogger("bootstrap")


def init_db() -> None:
    """建表（生产建议改用 Alembic 迁移，骨架阶段用 create_all）。"""
    Base.metadata.create_all(bind=engine)
    log.info("DB tables ensured")


def bootstrap_admin(db: Session) -> None:
    """P23：定死一个初始管理员账号密码。"""
    exists = db.query(User).filter(User.username == settings.BOOTSTRAP_ADMIN_USERNAME).first()
    if exists:
        return
    admin = User(
        username=settings.BOOTSTRAP_ADMIN_USERNAME,
        password_hash=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
        display_name=settings.BOOTSTRAP_ADMIN_DISPLAY,
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    log.warning(
        "BOOTSTRAP admin created: username=%s password=%s (change via 配置中心/用户管理!)",
        settings.BOOTSTRAP_ADMIN_USERNAME,
        settings.BOOTSTRAP_ADMIN_PASSWORD,
    )


def bootstrap_standard_evaluator(db: Session) -> None:
    """确保存在唯一标准评估器（无指标，待管理员在评估体系页维护）。"""
    exists = db.query(Evaluator).filter(Evaluator.is_standard.is_(True)).first()
    if exists:
        return
    ev = Evaluator(
        name="标准评估器",
        description="平台统一评分标准（由管理员维护指标与权重）",
        is_standard=True,
    )
    db.add(ev)
    db.commit()
    log.info("Standard evaluator bootstrapped: id=%s", ev.id)

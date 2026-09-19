import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.config import settings
from ..core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class FlowTemplate(Base):
    """测试执行流程模板（原 apiChain 的 chain.json），管理员配多套成模板池。"""
    __tablename__ = "flow_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    chain_json: Mapped[dict] = mapped_column(JSONB, nullable=False)  # API定义/步骤/全局变量/认证/超时/重试/extract
    # 被测 Agent 并发上限（与模板绑定，建任务时写入 Run.target_concurrency）
    target_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=settings.CONCURRENCY_TARGET)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    param_perms: Mapped[list["FlowTemplateParamPerm"]] = relationship(back_populates="template", cascade="all, delete-orphan")


class FlowTemplateParamPerm(Base):
    """模板中允许普通用户编辑的参数（P13）。"""
    __tablename__ = "flow_template_param_perms"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_templates.id"), primary_key=True
    )
    param_path: Mapped[str] = mapped_column(String(255), primary_key=True)  # 如 'apis[0].timeout'
    user_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    template: Mapped["FlowTemplate"] = relationship(back_populates="param_perms")

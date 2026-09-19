import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Report(Base):
    """代码聚合生成的报告（P17）。"""
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    standard_metric_averages: Mapped[list | None] = mapped_column(JSONB)
    extra_metric_averages: Mapped[list | None] = mapped_column(JSONB)
    dimension_summary: Mapped[list | None] = mapped_column(JSONB)  # P24: 按一/二级维度汇总
    case_details: Mapped[list | None] = mapped_column(JSONB)
    failure_root_causes: Mapped[list | None] = mapped_column(JSONB)  # [{category, count}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Evaluator(Base):
    """系统只有一个标准评估器（is_standard=TRUE 唯一）。"""
    __tablename__ = "evaluators"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_standard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    metrics: Mapped[list["EvaluatorMetric"]] = relationship(back_populates="evaluator", cascade="all, delete-orphan")


class EvaluatorMetric(Base):
    __tablename__ = "evaluator_metrics"

    evaluator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluators.id"), primary_key=True
    )
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("metrics.id"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)  # Σweight = 1
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    evaluator: Mapped["Evaluator"] = relationship(back_populates="metrics")

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="excel")
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)  # 表头→标准字段映射（P24）
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    cases: Mapped[list["Case"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True
    )
    case_no: Mapped[str] = mapped_column(String(128), nullable=False)        # 用例编号(必填)
    user_input: Mapped[str] = mapped_column(Text, nullable=False)            # 测试输入(必填)
    expected_gt: Mapped[str] = mapped_column(Text, nullable=False)           # 预期结果(必填)
    dimension_l1: Mapped[str | None] = mapped_column(String(128))            # 评测一级维度(可选)
    dimension_l2: Mapped[str | None] = mapped_column(String(128))            # 评测二级维度(可选)
    preset: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSONB)
    extra: Mapped[dict | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 轮次编号（exec 任务创建时按 sort_order 顺序 + round_size 计算）
    round_no: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    dataset: Mapped["Dataset"] = relationship(back_populates="cases")

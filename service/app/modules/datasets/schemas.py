"""数据集 / 用例相关请求响应模型。"""
from datetime import datetime

from pydantic import BaseModel, field_validator

from ..shared import _uuid_to_str


class ColumnMapping(BaseModel):
    case_no: str
    user_input: str
    expected_gt: str
    dimension_l1: str | None = None
    dimension_l2: str | None = None


class DatasetOut(BaseModel):
    id: str
    name: str
    case_count: int
    source: str
    owner_id: str
    username: str | None = None
    created_at: datetime

    @field_validator("id", "owner_id", mode="before")
    @classmethod
    def _ids(cls, v):
        return _uuid_to_str(cls, v)

    class Config:
        from_attributes = True


class CaseOut(BaseModel):
    id: str
    case_no: str
    user_input: str
    expected_gt: str
    dimension_l1: str | None
    dimension_l2: str | None
    preset: str | None
    steps: str | None
    tags: list | None
    extra: dict | None

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return _uuid_to_str(cls, v)

    class Config:
        from_attributes = True


class DatasetPreviewOut(BaseModel):
    dataset_id: str
    name: str
    case_count: int
    headers: list[str]
    rows: list[list]  # 前 5 行

    @field_validator("dataset_id", mode="before")
    @classmethod
    def _dsid(cls, v):
        return _uuid_to_str(cls, v)


class DatasetNameUpdateReq(BaseModel):
    name: str


class DatasetBatchDeleteReq(BaseModel):
    ids: list[str]


class DatasetListOut(BaseModel):
    items: list[DatasetOut]
    page: int
    page_size: int
    total: int


class CaseListOut(BaseModel):
    items: list[CaseOut]
    page: int
    page_size: int
    total: int


class CaseBatchGetReq(BaseModel):
    case_nos: list[str]

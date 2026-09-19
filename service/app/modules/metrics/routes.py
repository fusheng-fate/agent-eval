"""指标库：列表/详情（所有人）+ 增删改（仅管理员，P5）。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.deps import get_current_user, require_admin
from ...models import EvaluatorMetric, Metric, User
from ..shared import ok
from .schemas import MetricCreateReq, MetricListOut, MetricOut, MetricUpdateReq

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
def list_metrics(
    category: str | None = None,
    industry: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20
    q = db.query(Metric)
    if category:
        q = q.filter(Metric.category == category)
    if industry:
        q = q.filter(Metric.industry == industry)
    if keyword:
        q = q.filter(Metric.name.ilike(f"%{keyword}%"))
    total = q.count()
    items = q.order_by(Metric.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    data = MetricListOut(items=items, page=page, page_size=page_size, total=total)
    return ok(data.model_dump())


@router.get("/options")
def metric_options(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """轻量指标选项列表（id + name），供下拉选择使用。"""
    rows = db.query(Metric.id, Metric.name).order_by(Metric.name).all()
    return ok([{"id": str(r[0]), "name": r[1]} for r in rows])


@router.get("/{metric_id}")
def get_metric(metric_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    m = db.get(Metric, metric_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "指标不存在")
    return ok(MetricOut.model_validate(m).model_dump())


@router.post("", status_code=201)
def create_metric(req: MetricCreateReq, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(Metric).filter(Metric.name == req.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "指标名已存在")
    m = Metric(**req.model_dump(), created_by=admin.id)
    db.add(m)
    db.commit()
    db.refresh(m)
    return ok(MetricOut.model_validate(m).model_dump())


@router.post("/{metric_id}/update")
def update_metric(metric_id: uuid.UUID, req: MetricUpdateReq, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    m = db.get(Metric, metric_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "指标不存在")
    for k, v in req.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return ok(MetricOut.model_validate(m).model_dump())


@router.post("/{metric_id}/delete")
def delete_metric(metric_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    m = db.get(Metric, metric_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "指标不存在")
    ref = db.query(EvaluatorMetric).filter(EvaluatorMetric.metric_id == metric_id).first()
    if ref:
        raise HTTPException(status.HTTP_409_CONFLICT, "指标正被标准评估器引用，请先移除")
    db.delete(m)
    db.commit()
    return ok()

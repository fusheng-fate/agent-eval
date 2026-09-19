"""标准评估器：查看（所有人）+ 编辑（仅管理员，P4）。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.deps import get_current_user, require_admin
from ...models import Evaluator, EvaluatorMetric, Metric, User
from ..shared import ok
from .schemas import StandardEvaluatorOut, StandardEvaluatorUpdateReq

router = APIRouter(prefix="/evaluators", tags=["evaluators"])


def _standard(db: Session) -> Evaluator:
    ev = db.query(Evaluator).filter(Evaluator.is_standard.is_(True)).first()
    if ev is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "标准评估器未初始化")
    return ev


def _to_out(ev: Evaluator, db: Session) -> dict:
    metrics = []
    for em in sorted(ev.metrics, key=lambda x: x.sort_order):
        m = db.get(Metric, em.metric_id)
        metrics.append({
            "metricId": str(em.metric_id), "name": m.name, "category": m.category,
            "industry": m.industry, "description": m.description,
            "weight": float(em.weight),
        })
    return StandardEvaluatorOut(id=str(ev.id), name=ev.name, description=ev.description, metrics=metrics).model_dump()


@router.get("/standard")
def get_standard(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return ok(_to_out(_standard(db), db))


@router.post("/standard/update")
def update_standard(req: StandardEvaluatorUpdateReq, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    ev = _standard(db)
    total = sum(m.weight for m in req.metrics)
    if abs(total - 1) > 0.005:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"权重和须为 1，当前 {total}")
    for m in req.metrics:
        if db.get(Metric, uuid.UUID(m.metric_id)) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"指标不存在: {m.metric_id}")
    if req.description is not None:
        ev.description = req.description
    # 重建权重关系
    db.query(EvaluatorMetric).filter(EvaluatorMetric.evaluator_id == ev.id).delete()
    for i, m in enumerate(req.metrics):
        db.add(EvaluatorMetric(
            evaluator_id=ev.id, metric_id=uuid.UUID(m.metric_id),
            weight=m.weight, sort_order=i,
        ))
    db.commit()
    return ok(_to_out(ev, db))

"""测试执行流程模板：列表/详情（所有人）+ 增删改（仅管理员，P13）。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.deps import get_current_user, require_admin
from ...models import FlowTemplate, FlowTemplateParamPerm, Run, User
from ..shared import ok
from .schemas import FlowTemplateCreateReq, FlowTemplateOut

router = APIRouter(prefix="/flow-templates", tags=["flow-templates"])


def _to_out(t: FlowTemplate) -> dict:
    return FlowTemplateOut(
        id=str(t.id), name=t.name, description=t.description, chain_json=t.chain_json,
        target_concurrency=t.target_concurrency,
        param_perms=[{"paramPath": p.param_path, "userEditable": p.user_editable} for p in t.param_perms],
        created_at=t.created_at,
    ).model_dump()


@router.get("")
def list_templates(
    keyword: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(FlowTemplate)
    if keyword:
        q = q.filter(FlowTemplate.name.ilike(f"%{keyword}%"))
    # 无分页参数时返回全量数组（兼容旧调用）；有则返回分页结构
    if page is None and page_size is None:
        items = [_to_out(t) for t in q.order_by(FlowTemplate.created_at).all()]
        return ok(items)
    if page is None:
        page = 1
    if page_size is None or page_size < 1 or page_size > 100:
        page_size = 20
    total = q.count()
    items = [_to_out(t) for t in q.order_by(FlowTemplate.created_at).offset((page - 1) * page_size).limit(page_size).all()]
    return ok({"items": items, "page": page, "page_size": page_size, "total": total})


@router.get("/{template_id}")
def get_template(template_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    t = db.get(FlowTemplate, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    return ok(_to_out(t))


@router.post("", status_code=201)
def create_template(req: FlowTemplateCreateReq, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    t = FlowTemplate(name=req.name, description=req.description, chain_json=req.chain_json,
                     target_concurrency=req.target_concurrency, created_by=admin.id)
    db.add(t)
    db.flush()
    for p in req.param_perms:
        db.add(FlowTemplateParamPerm(template_id=t.id, param_path=p["paramPath"], user_editable=p.get("userEditable", False)))
    db.commit()
    db.refresh(t)
    return ok(_to_out(t))


@router.post("/{template_id}/update")
def update_template(template_id: uuid.UUID, req: FlowTemplateCreateReq, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    t = db.get(FlowTemplate, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    t.name = req.name
    t.description = req.description
    t.chain_json = req.chain_json
    t.target_concurrency = req.target_concurrency
    db.query(FlowTemplateParamPerm).filter(FlowTemplateParamPerm.template_id == template_id).delete()
    for p in req.param_perms:
        db.add(FlowTemplateParamPerm(template_id=t.id, param_path=p["paramPath"], user_editable=p.get("userEditable", False)))
    db.commit()
    db.refresh(t)
    return ok(_to_out(t))


@router.post("/{template_id}/delete")
def delete_template(template_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    t = db.get(FlowTemplate, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    # 活跃任务（等待/运行/暂停）引用中的模板禁止删除；已完成/已停止/异常的可删
    active_refs = (
        db.query(Run)
        .filter(Run.flow_template_id == template_id, Run.status.in_(["pending", "running", "paused"]))
        .count()
    )
    if active_refs > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, f"模板被 {active_refs} 个进行中任务引用，无法删除")
    db.delete(t)
    db.commit()
    return ok()


@router.post("/{template_id}/validate")
def validate_template(template_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    t = db.get(FlowTemplate, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    cj = t.chain_json or {}
    apis = {a.get("id") for a in cj.get("apis", [])}
    steps = cj.get("steps", [])
    for step in steps:
        if step.get("api_id") not in apis:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"步骤引用了不存在的 API: {step.get('api_id')}")
    # 校验 api.extract_to_result（{字段名: JSONPath}，回写 case_results 的 node_id/trace_no）
    for api in cj.get("apis", []):
        etr = api.get("extract_to_result")
        if etr is None:
            continue
        if not isinstance(etr, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"API {api.get('id')} 的 extract_to_result 必须是 {{字段名: JSONPath}} 对象")
        for field_name, path in etr.items():
            if not isinstance(path, str) or not path.strip():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"API {api.get('id')} 的 extract_to_result[{field_name}] 必须是非空 JSONPath 字符串")
    # 校验 final_extract（string 或 dict 形态）
    fe = cj.get("final_extract")
    if fe is not None:
        if isinstance(fe, str):
            if not fe.strip():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "final_extract 字符串不能为空")
        elif isinstance(fe, dict):
            last_idx = len(steps) - 1
            for field_name, spec in fe.items():
                if not isinstance(spec, dict):
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        f"final_extract[{field_name}] 必须是 {{step, path}} 对象")
                idx = spec.get("step", last_idx)
                if not isinstance(idx, int) or idx < 0 or idx >= len(steps):
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        f"final_extract[{field_name}].step={idx} 超出步骤范围 [0, {last_idx}]")
                if not spec.get("path"):
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        f"final_extract[{field_name}].path 不能为空")
        else:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "final_extract 必须是 string 或 dict")
    return ok({"message": f"校验通过：{len(apis)} 个 API，{len(steps)} 个步骤"})

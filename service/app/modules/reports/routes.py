"""报告中心：列表 / 详情 / 导出 HTML（P17/P26）。"""
import uuid

import io
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.deps import get_current_user, require_admin
from ...core.redis_client import get_redis
from ...models import Report, User
from ..shared import ApiResp, Msg, PageData, ok
from .report_service import render_html
from .schemas import ReportCompareOut, ReportOut

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ApiResp[PageData[ReportOut]])
def list_reports(
    keyword: str | None = None,
    username: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(Report)
    if keyword:
        q = q.filter(Report.task_name.ilike(f"%{keyword}%"))
    if username:
        q = q.join(User, Report.owner_id == User.id).filter(User.username == username)
    total = q.count()
    reports = q.order_by(Report.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    owner_ids = {r.owner_id for r in reports}
    user_map = {u.id: u.username for u in db.query(User).filter(User.id.in_(owner_ids)).all()} if owner_ids else {}
    items = []
    for r in reports:
        out = ReportOut.model_validate(r)
        out.username = user_map.get(r.owner_id)
        items.append(out)
    return ok(PageData(items=items, page=page, page_size=page_size, total=total))


@router.get("/compare", response_model=ApiResp[ReportCompareOut])
def compare_reports(a: str, b: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """对比两份报告：指标均分差异 + 用例明细差异。"""
    rep_a = db.get(Report, uuid.UUID(a))
    rep_b = db.get(Report, uuid.UUID(b))
    if rep_a is None or rep_b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")

    def _brief(rep: Report) -> dict:
        return {
            "id": str(rep.id),
            "task_name": rep.task_name,
            "summary": rep.summary,
            "standard_metric_averages": rep.standard_metric_averages,
        }

    metric_diff = []
    avg_a = {m["name"]: m["avgScore"] for m in (rep_a.standard_metric_averages or [])}
    avg_b = {m["name"]: m["avgScore"] for m in (rep_b.standard_metric_averages or [])}
    for name in sorted(set(avg_a) | set(avg_b)):
        sa, sb = avg_a.get(name), avg_b.get(name)
        metric_diff.append({
            "name": name,
            "a_score": sa,
            "b_score": sb,
            "delta": round((sb or 0) - (sa or 0), 3) if sa is not None and sb is not None else None,
        })

    case_diff = []
    cases_a = {c["caseNo"]: c for c in (rep_a.case_details or [])}
    cases_b = {c["caseNo"]: c for c in (rep_b.case_details or [])}
    for case_no in sorted(set(cases_a) | set(cases_b)):
        ca, cb = cases_a.get(case_no), cases_b.get(case_no)
        case_diff.append({
            "case_no": case_no,
            "a_status": ca["status"] if ca else None,
            "b_status": cb["status"] if cb else None,
            "a_score": ca.get("overallScore") if ca else None,
            "b_score": cb.get("overallScore") if cb else None,
        })

    return ok(ReportCompareOut(a=_brief(rep_a), b=_brief(rep_b), metric_diff=metric_diff, case_diff=case_diff))


@router.get("/share/{token}")
def view_shared_report(token: str, db: Session = Depends(get_db)):
    """公开端点：用 token 查看报告 HTML（无需登录）。"""
    report_id = get_redis().get(f"agent_eval:share:{token}")
    if not report_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分享链接无效或已过期")
    rep = db.get(Report, uuid.UUID(report_id))
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    html = render_html(rep)
    return HTMLResponse(content=html)


@router.get("/{report_id}", response_model=ApiResp[ReportOut])
def get_report(report_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    rep = db.get(Report, report_id)
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    return ok(ReportOut.model_validate(rep))


@router.get("/{report_id}/export.html")
def export_html(report_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    rep = db.get(Report, report_id)
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    html = render_html(rep)
    return HTMLResponse(content=html)


@router.get("/{report_id}/export.pdf")
def export_pdf(report_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """PDF 导出（reportlab）。"""
    rep = db.get(Report, report_id)
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    buf = io.BytesIO()
    _render_pdf(rep, buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report_{report_id}.pdf"},
    )


def _render_pdf(rep: Report, buf: io.BytesIO) -> None:
    """用 reportlab 生成报告 PDF（中文字体用系统 SimHei 或默认 Helvetica）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors

    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm)
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    body = styles["BodyText"]
    elements = []

    # 标题
    elements.append(Paragraph(f"评测报告：{rep.task_name}", h1))
    elements.append(Spacer(1, 6))

    # 摘要 KPI
    s = rep.summary or {}
    kpi_data = [["总用例", "通过", "失败", "均分", "Token", "均延迟"]]
    kpi_data.append([
        str(s.get("total", "-")), str(s.get("passed", "-")), str(s.get("failed", "-")),
        str(s.get("overallScore", "-")), str(s.get("tokenUsage", "-")),
        f"{s.get('avgLatencySec', '-')}s",
    ])
    kpi_table = Table(kpi_data, colWidths=[30 * mm] * 6)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#C7000B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 12))

    # 标准指标均分
    if rep.standard_metric_averages:
        elements.append(Paragraph("标准指标均分", styles["Heading2"]))
        rows = [["指标", "权重", "均分"]]
        for m in rep.standard_metric_averages:
            rows.append([m["name"], str(m.get("weight", "")), str(m.get("avgScore", ""))])
        t = Table(rows, colWidths=[50 * mm, 30 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EBEFF5")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 12))

    # 用例明细
    if rep.case_details:
        elements.append(Paragraph("用例明细", styles["Heading2"]))
        rows = [["用例", "状态", "均分", "Token", "延迟(s)"]]
        for c in rep.case_details[:50]:  # 限 50 行防 PDF 过大
            rows.append([
                c.get("case_no", ""), c.get("status", ""),
                str(c.get("overall_score", "")), str(c.get("token_usage", "")),
                str(c.get("latency_sec", "")),
            ])
        t = Table(rows, colWidths=[30 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EBEFF5")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        elements.append(t)

    doc.build(elements)


@router.post("/{report_id}/share", response_model=ApiResp[dict])
def share_report(report_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """生成分享链接（token 存 Redis，TTL 7 天，无需登录即可查看）。"""
    rep = db.get(Report, report_id)
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    token = secrets.token_urlsafe(32)
    get_redis().setex(f"agent_eval:share:{token}", 7 * 24 * 3600, str(report_id))
    return ok({"share_url": f"/api/reports/share/{token}", "token": token, "expires_in_days": 7})


@router.post("/{report_id}/delete", response_model=ApiResp[None])
def delete_report(report_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    # Q2 已定：仅管理员可删除报告，普通用户不可删除
    rep = db.get(Report, report_id)
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    db.delete(rep)
    db.commit()
    return ok(None)

"""结果导出（P26）：在原 Excel 列基础上加列，导出 .xlsx。

- level=exec：原列 + 「执行结果」列（被测 Agent 返回）。
- level=eval：exec 基础上 + 「评测得分」+「简短评价」列。
"""
import io
import logging

from openpyxl import Workbook
from sqlalchemy.orm import Session

from ...models import Case, CaseResult, Run

log = logging.getLogger("export")

BASE_HEADERS = ["用例编号", "测试输入", "预期结果", "评测一级维度", "评测二级维度"]


def export_run_excel(db: Session, run: Run, level: str) -> bytes:
    results = {
        r.case_id: r for r in
        db.query(CaseResult).filter(CaseResult.run_id == run.id).all()
    }
    cases = db.query(Case).filter(Case.id.in_(list(results.keys()))).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "评测结果"

    headers = list(BASE_HEADERS)
    if level in ("exec", "eval"):
        headers.append("执行结果")
    if level == "eval":
        headers += ["评测得分", "简短评价", "失败归因"]
    headers += ["node_id", "trace_no"]
    if level in ("exec", "eval"):
        headers += ["执行开始时间", "执行结束时间"]
    ws.append(headers)

    from datetime import timezone, timedelta
    _CST = timezone(timedelta(hours=8))

    def _fmt_ts(v):
        if not v:
            return ""
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(_CST).strftime("%Y-%m-%d %H:%M:%S")

    for c in cases:
        r = results.get(c.id)
        row = [c.case_no, c.user_input, c.expected_gt, c.dimension_l1 or "", c.dimension_l2 or ""]
        if level in ("exec", "eval"):
            row.append((r.agent_output if r else "") or "")
        if level == "eval":
            row.append(float(r.overall_score) if r and r.overall_score is not None else "")
            row.append((r.brief_comment if r else "") or "")
            row.append((r.failure_attribution.get("primary", "") if r and r.failure_attribution else "") or "")
        row.append((r.node_id if r else "") or "")
        row.append((r.trace_no if r else "") or "")
        if level in ("exec", "eval"):
            row.append(_fmt_ts(r.exec_started_at if r else None))
            row.append(_fmt_ts(r.exec_finished_at if r else None))
        ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

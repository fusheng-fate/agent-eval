"""报告聚合（P17：代码直接合成，不调 skill）+ HTML 导出（P26）。"""
import logging
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from ...models import Case, CaseResult, Dataset, Evaluator, EvaluatorMetric, Metric, Report, Run

log = logging.getLogger("report")


def _case_detail(r: CaseResult, c: Case | None) -> dict:
    """聚合单条用例的明细字段（维度汇总 / 失败归因展开行用）。

    对齐前端报告详情页展开行的 4 个字段：测试输入 / 预期结果 / 测试输出 / 打分理由。
    """
    return {
        "caseNo": c.case_no if c else "",
        "status": r.status,
        "overallScore": float(r.overall_score) if r.overall_score is not None else None,
        "userInput": c.user_input if c else None,
        "expectedGt": c.expected_gt if c else None,
        "agentOutput": r.agent_output,
        "briefComment": r.brief_comment,
    }


def build_report(db: Session, run: Run) -> Report:
    """根据 case_results 聚合出报告并落库。"""
    results = db.query(CaseResult).filter(CaseResult.run_id == run.id).all()
    cases = {c.id: c for c in db.query(Case).filter(Case.id.in_([r.case_id for r in results])).all()}
    evaluator = db.get(Evaluator, run.evaluator_id)
    dataset = db.get(Dataset, run.dataset_id)

    total = len(results)
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    scores = [float(r.overall_score) for r in results if r.overall_score is not None]
    overall = round(sum(scores) / len(scores), 3) if scores else 0
    latencies = [float(r.latency_sec) for r in results if r.latency_sec is not None]
    tokens = sum(r.token_usage or 0 for r in results)

    summary = {
        "overallScore": overall, "total": total, "passed": passed, "failed": failed,
        "tokenUsage": tokens, "avgLatencySec": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "execSec": float(run.exec_sec) if run.exec_sec is not None else None,
        "scoreSec": float(run.score_sec) if run.score_sec is not None else None,
    }

    # 标准指标均分
    std_averages = []
    for em in evaluator.metrics:
        metric = db.get(Metric, em.metric_id)
        vals = [
            m["score"] for r in results for m in (r.standard_metrics or [])
            if m.get("metricId") == str(em.metric_id)
        ]
        std_averages.append({
            "metricId": str(em.metric_id), "name": metric.name,
            "weight": float(em.weight),
            "avgScore": round(sum(vals) / len(vals), 3) if vals else 0,
        })

    # 额外指标均分
    extra_ids = list(run.extra_metric_ids or [])
    extra_averages = []
    for mid in extra_ids:
        metric = db.get(Metric, mid)
        if metric is None:
            continue
        vals = [
            m["score"] for r in results for m in (r.extra_metrics or [])
            if m.get("metricId") == str(mid)
        ]
        extra_averages.append({
            "metricId": str(mid), "name": metric.name,
            "avgScore": round(sum(vals) / len(vals), 3) if vals else 0,
        })

    # 维度汇总（P24）
    dim: dict[tuple, list] = defaultdict(list)
    for r in results:
        c = cases.get(r.case_id)
        if c and (c.dimension_l1 or c.dimension_l2):
            dim[(c.dimension_l1 or "-", c.dimension_l2 or "-")].append(r)
    dimension_summary = []
    for (l1, l2), rs in dim.items():
        sc = [float(r.overall_score) for r in rs if r.overall_score is not None]
        dim_cases = []
        for r in rs:
            c = cases.get(r.case_id)
            dim_cases.append(_case_detail(r, c))
        dimension_summary.append({
            "l1": l1, "l2": l2, "total": len(rs),
            "passed": sum(1 for r in rs if r.status == "passed"),
            "failed": sum(1 for r in rs if r.status == "failed"),
            "avgScore": round(sum(sc) / len(sc), 3) if sc else 0,
            "cases": dim_cases,
        })

    case_details = []
    for r in results:
        c = cases.get(r.case_id)
        case_details.append({
            "caseId": str(r.case_id), "caseNo": c.case_no if c else "",
            "status": r.status, "overallScore": float(r.overall_score) if r.overall_score else None,
            "standardMetrics": r.standard_metrics, "extraMetrics": r.extra_metrics,
            "userInput": c.user_input if c else None,
            "expectedGt": c.expected_gt if c else None,
            "agentOutput": r.agent_output,
            "briefComment": r.brief_comment,
            "failureAttribution": r.failure_attribution,
        })

    # 失败归因分布：统计 failed 用例的 primary 分类
    attr_counter: Counter[str] = Counter()
    attr_cases: dict[str, list] = defaultdict(list)
    for r in results:
        if r.status == "failed" and r.failure_attribution:
            primary = r.failure_attribution.get("primary")
            if primary:
                attr_counter[primary] += 1
                c = cases.get(r.case_id)
                attr_cases[primary].append(_case_detail(r, c))
    failure_root_causes = [
        {"category": cat, "count": cnt, "cases": attr_cases.get(cat, [])}
        for cat, cnt in attr_counter.most_common()
    ]

    # 幂等：同一 run 只留一份报告
    existing = db.query(Report).filter(Report.run_id == run.id).first()
    if existing:
        rep = existing
    else:
        rep = Report(run_id=run.id, task_name=run.task_name, owner_id=run.owner_id)
        db.add(rep)
    rep.summary = summary
    rep.standard_metric_averages = std_averages
    rep.extra_metric_averages = extra_averages
    rep.dimension_summary = dimension_summary
    rep.case_details = case_details
    rep.failure_root_causes = failure_root_causes
    db.commit()
    log.info("report built for run %s: id=%s", run.id, rep.id)
    return rep


def _esc(v) -> str:
    """HTML 转义（防注入：用例输入/输出可能含 <>&"）。"""
    if v is None:
        return ""
    return (
        str(v)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _status_badge(status: str) -> str:
    cls = {"passed": "ok", "failed": "bad", "error": "bad"}.get(status, "warn")
    label = {"passed": "通过", "failed": "失败", "error": "异常"}.get(status, status)
    return f'<span class="badge {cls}">{_esc(label)}</span>'


def _fmt_score(v) -> str:
    """分数展示（后端百分制，最多 2 位；None → -）。"""
    if v is None:
        return "-"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "-"
    return str(round(n * 100) / 100)


def _case_detail_table(cases: list, uid: str) -> str:
    """用例明细表格：用例/状态/加权分数/测试输入/预期结果/测试输出/打分理由。
    样式对齐前端报告详情页（长文本截断 2 行，点击展开），带纯前端翻页。
    uid 用于给本页控件加唯一 id（自包含 HTML 内可能并存多张明细表）。"""
    total = len(cases or [])
    rows = []
    for c in cases or []:
        def cell(key):
            v = (c.get(key) or "").strip() if isinstance(c.get(key), str) else (c.get(key) or "")
            if not v:
                return '<span class="ct-empty">-</span>'
            return f'<span class="ct-clamp" onclick="ctToggle(this)">{_esc(v)}</span>'
        rows.append(
            f"<tr class='ct-row'>"
            f'<td class="ct-case">{_esc(c.get("caseNo"))}</td>'
            f"<td>{_status_badge(c.get('status'))}</td>"
            f"<td>{_fmt_score(c.get('overallScore'))}</td>"
            f"<td>{cell('userInput')}</td>"
            f"<td>{cell('expectedGt')}</td>"
            f"<td>{cell('agentOutput')}</td>"
            f"<td>{cell('briefComment')}</td>"
            f"</tr>"
        )
    pager = ""
    if total > 0:
        pager = (
            f'<div class="ct-pager">'
            f'<button class="ct-btn" data-uid="{uid}" onclick="ctPrev(this)">‹</button>'
            f'<span class="ct-pageinfo" id="ct-info-{uid}">1 / 1</span>'
            f'<button class="ct-btn" data-uid="{uid}" onclick="ctNext(this)">›</button>'
            f"</div>"
        )
    return (
        f'<div class="ct-wrap" id="ct-wrap-{uid}">'
        f'<table class="case-detail-table"><thead><tr>'
        "<th>用例</th><th>状态</th><th>加权分数</th><th>测试输入</th>"
        "<th>预期结果</th><th>测试输出</th><th>打分理由</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"{pager}</div>"
    )


def render_html(report: Report) -> str:
    """导出自包含 HTML（P26）。样式对齐 docs/DESIGN.md（华为云上 OpenLab）。"""
    s = report.summary or {}
    total = s.get("total") or 0
    passed = s.get("passed") or 0
    pass_rate = round(passed / total * 100, 1) if total else 0

    kpis = f"""
      <div class="kpi"><div class="kpi-num">{_esc(s.get('overallScore', 0))}</div><div class="kpi-label">主分</div></div>
      <div class="kpi"><div class="kpi-num">{_esc(total)}</div><div class="kpi-label">用例</div></div>
      <div class="kpi"><div class="kpi-num">{_esc(passed)}</div><div class="kpi-label">通过</div></div>
      <div class="kpi"><div class="kpi-num">{_esc(s.get('failed', 0))}</div><div class="kpi-label">失败</div></div>
      <div class="kpi"><div class="kpi-num">{_esc(pass_rate)}%</div><div class="kpi-label">通过率</div></div>
      <div class="kpi"><div class="kpi-num">{_esc(s.get('avgLatencySec', 0))}</div><div class="kpi-label">平均耗时(s)</div></div>
      <div class="kpi"><div class="kpi-num">{_esc(s.get('tokenUsage', 0))}</div><div class="kpi-label">Token</div></div>
    """

    def _metric_rows(items: list, with_weight: bool):
        rows = []
        for m in items or []:
            w = f'<td>{_esc(m.get("weight"))}</td>' if with_weight else ""
            rows.append(
                f"<tr><td>{_esc(m.get('name'))}</td>{w}"
                f"<td>{_esc(m.get('avgScore'))}</td></tr>"
            )
        return "".join(rows) or '<tr><td colspan="3" class="empty">无</td></tr>'

    std_table = (
        f'<table><thead><tr><th>指标</th><th>权重</th><th>均分</th></tr></thead>'
        f"<tbody>{_metric_rows(report.standard_metric_averages, True)}</tbody></table>"
    )
    extra_table = (
        f'<table><thead><tr><th>指标</th><th>均分</th></tr></thead>'
        f"<tbody>{_metric_rows(report.extra_metric_averages, False)}</tbody></table>"
    )

    # 维度汇总：最后一列「明细」放按钮，点击在下方展开用例明细表格（样式对齐前端）
    dim_rows = []
    for i, d in enumerate(report.dimension_summary or []):
        dim_cases = d.get("cases") or []
        if dim_cases:
            btn = f'<button class="detail-btn" data-ns="dim" data-n="{len(dim_cases)}" onclick="toggleDetail(this,{i})">查看 {len(dim_cases)} 条</button>'
            hidden = (
                f'<tr class="detail-row" id="dim-detail-{i}" style="display:none">'
                f'<td colspan="7">{_case_detail_table(dim_cases, f"dim{i}")}</td></tr>'
            )
        else:
            btn, hidden = "", ""
        dim_rows.append(
            f"<tr><td>{_esc(d.get('l1'))}</td><td>{_esc(d.get('l2'))}</td>"
            f"<td>{_esc(d.get('total'))}</td><td>{_esc(d.get('passed'))}</td>"
            f"<td>{_esc(d.get('failed'))}</td><td>{_esc(d.get('avgScore'))}</td>"
            f'<td class="detail-col">{btn}</td></tr>{hidden}'
        )
    dim_table = (
        f'<table><thead><tr><th>维度L1</th><th>维度L2</th><th>用例</th>'
        f"<th>通过</th><th>失败</th><th>均分</th><th>明细</th></tr></thead>"
        f"<tbody>{''.join(dim_rows) or '<tr><td colspan=7 class=empty>无</td></tr>'}</tbody></table>"
    )

    case_rows = []
    for cd in report.case_details or []:
        fa = cd.get("failureAttribution")
        fa_primary = _esc(fa.get("primary")) if fa else "—"
        case_rows.append(
            f"<tr><td>{_esc(cd.get('caseNo'))}</td>"
            f"<td>{_status_badge(cd.get('status'))}</td>"
            f"<td>{_esc(cd.get('overallScore'))}</td>"
            f"<td class='cell-clamp' title=\"{_esc(cd.get('userInput'))}\">{_esc(cd.get('userInput')) or '—'}</td>"
            f"<td class='cell-clamp' title=\"{_esc(cd.get('expectedGt'))}\">{_esc(cd.get('expectedGt')) or '—'}</td>"
            f"<td class='cell-clamp' title=\"{_esc(cd.get('agentOutput'))}\">{_esc(cd.get('agentOutput')) or '—'}</td>"
            f"<td>{_esc(cd.get('briefComment')) or '—'}</td>"
            f"<td>{fa_primary}</td></tr>"
        )
    case_table = (
        f'<table><thead><tr><th>用例编号</th><th>状态</th><th>主分</th><th>输入</th>'
        f"<th>预期结果</th><th>输出</th><th>评价</th><th>失败归因</th></tr></thead>"
        f"<tbody>{''.join(case_rows) or '<tr><td colspan=8 class=empty>无</td></tr>'}</tbody></table>"
    )

    # 失败归因分布：最后一列「明细」放按钮，点击在下方展开用例明细表格（样式对齐前端）
    frc = report.failure_root_causes or []
    if frc:
        frc_rows = []
        for i, item in enumerate(frc):
            frc_cases = item.get("cases") or []
            if frc_cases:
                btn = f'<button class="detail-btn" data-ns="frc" data-n="{len(frc_cases)}" onclick="toggleDetail(this,{i})">查看 {len(frc_cases)} 条</button>'
                hidden = (
                    f'<tr class="detail-row" id="frc-detail-{i}" style="display:none">'
                    f'<td colspan="3">{_case_detail_table(frc_cases, f"frc{i}")}</td></tr>'
                )
            else:
                btn, hidden = "", ""
            frc_rows.append(
                f"<tr><td>{_esc(item.get('category'))}</td><td>{item.get('count')}</td>"
                f'<td class="detail-col">{btn}</td></tr>{hidden}'
            )
        frc_card = (
            f'<div class="card"><h2>失败归因分布</h2>'
            f'<table><thead><tr><th>归因分类</th><th>数量</th><th>明细</th></tr></thead>'
            f'<tbody>{"".join(frc_rows)}</tbody></table></div>'
        )
    else:
        frc_card = ""

    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(report.task_name)} · 评测报告</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:'PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif;
background:#EBEFF5;color:#24282E;line-height:1.5;padding:40px 24px}}
.wrap{{max-width:1080px;margin:0 auto}}
.card{{background:#fff;border-radius:16px;padding:28px 32px;margin-bottom:24px}}
h1{{font-size:25px;font-weight:600;margin:0 0 4px;color:#24282E}}
.sub{{font-size:14px;color:#828994;margin:0 0 20px}}
h2{{font-size:19px;font-weight:600;color:#24282E;margin:0 0 16px}}
.kpis{{display:grid;grid-template-columns:repeat(7,1fr);gap:16px}}
.kpi{{background:#F5F7FA;border-radius:12px;padding:16px 8px;text-align:center}}
.kpi-num{{font-size:22px;font-weight:600;color:#24282E}}
.kpi-label{{font-size:13px;color:#828994;margin-top:4px}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:10px 12px;font-size:14px;text-align:left;border-bottom:1px solid #DCE0E6;color:#474E57}}
th{{color:#828994;font-weight:600;font-size:13px}}
td.empty{{color:#828994;text-align:center}}
td.cell-clamp{{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.badge{{display:inline-block;padding:2px 10px;border-radius:100px;font-size:12px;font-weight:500}}
.badge.ok{{background:#E7F7EC;color:#67C23A}}
.badge.bad{{background:#FDECEC;color:#F56C6C}}
.badge.warn{{background:#FDF6EC;color:#E6A23C}}
.detail-col{{white-space:nowrap}}
.detail-btn{{cursor:pointer;font-size:13px;color:#C7000B;font-weight:500;background:none;border:none;padding:0}}
.detail-btn:hover{{text-decoration:underline}}
.detail-row td{{padding:8px 16px 16px;background:#F5F7FA}}
.case-detail-table{{width:100%;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #DCE0E6}}
.case-detail-table th,.case-detail-table td{{padding:8px 12px;font-size:12px;border-bottom:1px solid #DCE0E6;vertical-align:top}}
.case-detail-table th{{color:#828994;font-weight:600;background:#F5F7FA}}
.case-detail-table td.ct-case{{font-weight:600;color:#24282E;white-space:nowrap}}
.case-detail-table .ct-empty{{color:#828994}}
.case-detail-table .ct-clamp{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;white-space:pre-wrap;word-break:break-all;cursor:pointer;color:#474E57}}
.case-detail-table .ct-clamp.open{{display:block;-webkit-line-clamp:unset;overflow:visible;cursor:default}}
.ct-pager{{display:flex;align-items:center;justify-content:flex-end;gap:10px;padding:10px 12px 2px}}
.ct-btn{{cursor:pointer;font-size:14px;line-height:1;color:#C7000B;background:#fff;border:1px solid #DCE0E6;border-radius:6px;width:28px;height:28px;padding:0}}
.ct-btn:hover{{border-color:#C7000B}}
.ct-btn:disabled{{color:#C4C9D0;border-color:#E5E8EC;cursor:not-allowed}}
.ct-pageinfo{{font-size:12px;color:#828994}}
@media(max-width:960px){{.kpis{{grid-template-columns:repeat(3,1fr)}}}}
</style>
<script>
function toggleDetail(btn,idx){{
  var row=document.getElementById((btn.dataset.ns||'dim')+'-detail-'+idx);
  if(!row)return;
  var open=row.style.display!=='none';
  row.style.display=open?'none':'';
  btn.textContent=open?'查看 '+(btn.dataset.n||'')+' 条':'收起';
}}
function ctToggle(el){{el.classList.toggle('open')}}
// 用例明细表格纯前端翻页（每页 10 条）
var CT_PAGE_SIZE=10, CT_STATE={{}};
function ctRender(uid){{
  var wrap=document.getElementById('ct-wrap-'+uid);
  if(!wrap)return;
  var rows=wrap.querySelectorAll('.ct-row');
  var total=rows.length, pages=Math.max(1,Math.ceil(total/CT_PAGE_SIZE));
  var st=CT_STATE[uid]||{{page:1}};
  if(st.page>pages)st.page=pages;
  var start=(st.page-1)*CT_PAGE_SIZE;
  for(var i=0;i<rows.length;i++){{rows[i].style.display=(i>=start&&i<start+CT_PAGE_SIZE)?'':'none';}}
  var info=document.getElementById('ct-info-'+uid);
  if(info)info.textContent=st.page+' / '+pages;
  var btns=wrap.querySelectorAll('.ct-btn');
  for(var b=0;b<btns.length;b++){{btns[b].disabled=(btns[b].getAttribute('onclick').indexOf('ctPrev')===0)?st.page<=1:st.page>=pages;}}
  CT_STATE[uid]=st;
}}
function ctPrev(btn){{var uid=btn.dataset.uid;var st=CT_STATE[uid]||{{page:1}};if(st.page>1){{st.page--;CT_STATE[uid]=st;ctRender(uid);}}}}
function ctNext(btn){{var uid=btn.dataset.uid;var st=CT_STATE[uid]||{{page:1}};var wrap=document.getElementById('ct-wrap-'+uid);var pages=Math.max(1,Math.ceil(wrap.querySelectorAll('.ct-row').length/CT_PAGE_SIZE));if(st.page<pages){{st.page++;CT_STATE[uid]=st;ctRender(uid);}}}}
window.addEventListener('load',function(){{var wraps=document.querySelectorAll('.ct-wrap');for(var i=0;i<wraps.length;i++){{ctRender(wraps[i].id.replace('ct-wrap-',''));}}}});
</script>
<body><div class="wrap">
<div class="card">
  <h1>{_esc(report.task_name)}</h1>
  <p class="sub">评测报告 · 自包含导出</p>
  <div class="kpis">{kpis}</div>
</div>
<div class="card"><h2>标准指标均分</h2>{std_table}</div>
<div class="card"><h2>额外指标均分</h2>{extra_table}</div>
<div class="card"><h2>维度汇总</h2>{dim_table}</div>
{frc_card}
<div class="card"><h2>逐用例明细</h2>{case_table}</div>
</div></body></html>"""

# reports 模块

## 职责
报告中心（P17/P26）：列表、详情、导出 HTML。run 全部完成后由 worker 触发**代码聚合**（非 LLM）生成报告。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/reports` | 登录用户 | 列表（可按 keyword 筛选） |
| GET | `/api/reports/{id}` | 登录用户 | 详情 |
| GET | `/api/reports/{id}/export.html` | 登录用户 | 导出自包含 HTML |
| DELETE | `/api/reports/{id}` | **仅管理员**（Q2） | 删除报告（普通用户不可删） |

## 文件
- `routes.py` — 路由（4 接口）
- `schemas.py` — ReportOut
- `report_service.py` — build_report（代码聚合）+ render_html（HTML 导出）

## 依赖
- `app.core.database` — get_db
- `app.core.deps` — get_current_user
- `app.models.Report` / `CaseResult` / `Case` / `Dataset` / `Evaluator` / `EvaluatorMetric` / `Metric` / `Run`
- 被 `runs.worker` 跨模块调用（`build_report`）

## 数据模型
- `Report`（`app/models/report.py`）：run_id / task_name / owner_id / summary / standard_metric_averages / extra_metric_averages / dimension_summary / case_details / created_at

## 权限
- 读/导出：所有登录用户（报告全局可见）
- **删除：仅管理员**（Q2 已定：普通用户不能删除任务/报告，仅可暂停/继续/停止）

## 关键概念
- **代码聚合**（P17）：run 完成后 worker 调 `build_report`，根据 case_results 直接计算聚合（不调 LLM）
  - summary：overallScore / total / passed / failed / tokenUsage / avgLatencySec
  - standard_metric_averages：标准指标均分（含 weight）
  - extra_metric_averages：额外指标均分
  - dimension_summary：维度汇总（P24，按 dimension_l1/l2 分组）
  - case_details：逐用例明细
- **幂等**：同一 run 只留一份报告（existing 则更新，不新建）
- **HTML 导出**（P26）：自包含 HTML（内联 CSS），样式对齐 `docs/DESIGN.md`（华为红 `#C7000B` / 白卡 16px 圆角 / 蓝灰中性色 / 状态徽标）。KPI 卡 + 标准/额外指标均分 + 维度汇总 + 逐用例明细；全部文本经 `_esc` 转义防注入。

## 测试
- `tests/test_runs_reports.py`（在 `dev/service/tests/`）：报告聚合（summary/指标均分/维度/幂等）+ HTML 渲染（含注入转义）。

## TODO
- [x] HTML 报告套 DESIGN.md 样式（已实现：KPI 卡 + 指标/维度/明细表 + 状态徽标 + 转义）
- [ ] 报告 PDF 导出
- [ ] 报告对比（两个 run 的指标对比）
- [ ] 报告分享链接（当前仅登录用户可看）

## 协作守则
- `build_report` 被 runs.worker 跨模块调用，改签名需同步 worker。
- 聚合逻辑是纯计算（无副作用），可单测。
- HTML 导出是自包含的（无外部依赖），可直接发文件。

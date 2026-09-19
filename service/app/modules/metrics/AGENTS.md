# metrics 模块

## 职责
指标库：列表/详情（所有人只读）+ 增删改（仅管理员，P5）。指标是评估器的组成单元，含评分要求（skill_md）。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/metrics` | 登录用户 | 列表（可按 category/industry/keyword 筛选） |
| GET | `/api/metrics/{id}` | 登录用户 | 详情 |
| POST | `/api/metrics` | admin | 新建指标 |
| PUT | `/api/metrics/{id}` | admin | 更新指标 |
| DELETE | `/api/metrics/{id}` | admin | 删除指标（被标准评估器引用时 409） |

## 文件
- `routes.py` — 路由（5 接口）
- `schemas.py` — MetricOut / MetricCreateReq / MetricUpdateReq / MetricListOut

## 响应（统一包裹结构）
所有接口统一返回 `{code, message, data}`（见 `docs/服务化数据模型与接口.md` 的 API 响应规范）。

- 成功：`code=0, message="ok"`；`data` 为接口实际内容。
- 列表 `GET /metrics` 的 `data` 为分页结构 `{items, page, page_size, total}`（契约 2.3 要求 `?category=&industry=&keyword=&page=`）。
- 新建成功返回 HTTP 201。
- 异常（未认证/无权限/不存在/指标名重复/被引用）用 4xx，由全局中间件 `WrapErrorMiddleware` 包裹为 `{code, message, data}`。
- 通用辅助：`app.modules.shared` 的 `ok(data=None)`。

## 依赖
- `app.core.deps` — `get_current_user` / `require_admin`
- `app.models.Metric` / `app.models.EvaluatorMetric`（删除时校验引用）

## 数据模型
- `Metric`（`app/models/metric.py`）：name / category(tech|biz) / industry / description / skill_md / is_builtin / created_by / created_at
- `EvaluatorMetric`（`app/models/evaluator.py`）：指标与评估器的权重关系（删除校验用）

## 权限
- 读：所有登录用户
- 写：仅 admin
- 删除前校验：指标正被标准评估器引用（EvaluatorMetric 存在）则 409，需先从评估器移除

## 关键概念
- `skill_md`：指标的评分要求（自然语言），执行时拼入 LLM prompt 作为评分标准。
- `category`：tech（技术类）/ biz（业务类）
- `is_builtin`：内置指标标记（骨架阶段未区分，预留）

## TODO
- [ ] 指标分类字典管理（当前 category 硬编码 tech/biz）
- [ ] 指标导入/导出（批量）
- [ ] 指标版本管理（修改 skill_md 的历史追溯）

## 协作守则
- `skill_md` 内容直接进 LLM prompt，修改会影响评分结果，改前确认。
- 删除指标不影响已有 run 的历史结果（case_results 存的是快照）。

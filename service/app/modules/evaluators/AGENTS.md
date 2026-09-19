# evaluators 模块

## 职责
标准评估器：查看（所有人）+ 编辑（仅管理员，P4）。平台唯一标准评估器，由管理员维护指标与权重。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/evaluators/standard` | 登录用户 | 获取标准评估器（含指标+权重） |
| PUT | `/api/evaluators/standard` | admin | 更新标准评估器（重建权重关系） |

## 文件
- `routes.py` — 路由（2 接口）
- `schemas.py` — StandardEvaluatorOut / StandardEvaluatorUpdateReq / EvaluatorMetricIn

## 响应（统一包裹结构）
所有接口统一返回 `{code, message, data}`（见 `docs/服务化数据模型与接口.md` 的 API 响应规范）。

- 成功：`code=0, message="ok"`；`data` 为标准评估器对象（含 metrics 权重列表）。
- 异常（未认证/无权限/权重和不为1/指标不存在/未初始化）用 4xx/5xx，由全局中间件 `WrapErrorMiddleware` 包裹为 `{code, message, data}`。
- 通用辅助：`app.modules.shared` 的 `ok(data=None)`。

## 依赖
- `app.core.deps` — `get_current_user` / `require_admin`
- `app.models.Evaluator` / `app.models.EvaluatorMetric` / `app.models.Metric`

## 数据模型
- `Evaluator`（`app/models/evaluator.py`）：name / description / is_standard
- `EvaluatorMetric`（`app/models/evaluator.py`）：evaluator_id / metric_id / weight / sort_order

## 权限
- 读：所有登录用户
- 写：仅 admin
- 执行前必选且默认选标准评估器（P4），普通用户不可编辑

## 关键概念
- **加权评分**（P19）：指标分与主分均为百分制 0-100；`overallScore = Σ(标准指标分 × weight)`，`passed = overallScore >= pass_threshold`（阈值从配置中心 `report.pass_threshold` 读取，缺省 80）
- 权重和必须为 1（±0.005 容差），否则 422
- 更新时**重建** EvaluatorMetric 关系（先删后建），保证 sort_order 连续
- 额外指标（extra_metric_ids）不进标准评估器，在 run 创建时单独指定，单独计分

## TODO
- [ ] 评估器版本管理（修改权重的历史追溯）
- [ ] 非标准评估器支持（当前仅 is_standard=True 一个）
- [ ] 评估器模板/预设

## 协作守则
- 权重和校验是硬约束，前端也需校验（双保险）。
- 修改标准评估器不影响已有 run 的历史结果（run 创建时已快照 evaluator_id）。

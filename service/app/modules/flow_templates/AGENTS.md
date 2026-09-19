# flow_templates 模块

## 职责
测试执行流程模板（P13）：列表、详情、新建、更新、删除、校验。管理员配置几套模板作为"测试环境选择"，普通用户选模板后可调整部分参数。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/flow-templates` | 登录用户 | 列表 |
| GET | `/api/flow-templates/{id}` | 登录用户 | 详情（含 param_perms） |
| POST | `/api/flow-templates` | admin | 新建模板 |
| PUT | `/api/flow-templates/{id}` | admin | 更新模板（重建 param_perms） |
| DELETE | `/api/flow-templates/{id}` | admin | 删除（即使被 run 引用也可删） |
| POST | `/api/flow-templates/{id}/validate` | 登录用户 | 校验（步骤引用的 API 是否存在） |

## 文件
- `routes.py` — 路由（6 接口）
- `schemas.py` — FlowTemplateOut / FlowTemplateCreateReq

## 响应（统一包裹结构）
所有接口统一返回 `{code, message, data}`（见 `docs/服务化数据模型与接口.md` 的 API 响应规范）。

- 成功：`code=0, message="ok"`；`data` 为接口实际内容。
- 列表 `GET /flow-templates` 的 `data` 为模板数组（契约未要求分页）。
- 新建成功返回 HTTP 201。
- 异常（未认证/无权限/不存在/参数错）用 4xx，由全局中间件 `WrapErrorMiddleware` 包裹为 `{code, message, data}`。
- 通用辅助：`app.modules.shared` 的 `ok(data=None)`。

## 依赖
- `app.core.deps` — `get_current_user` / `require_admin`
- `app.models.FlowTemplate` / `app.models.FlowTemplateParamPerm` / `app.models.Run`（删除校验）

## 数据模型
- `FlowTemplate`（`app/models/flow_template.py`）：name / description / chain_json / target_concurrency（被测 Agent 并发上限，建任务时快照进 runs）/ created_by / created_at
- `FlowTemplateParamPerm`（`app/models/flow_template.py`）：template_id / param_path / user_editable

## 权限
- 读：所有登录用户
- 写：仅 admin
- 普通用户选模板后可调整 `user_editable=True` 的参数（在 run 创建时通过 overrides 传入）

## 关键概念
- **chain_json**：API 链路编排（沿用 apiChain 结构）
  ```json
  {
    "apis": [{id, method, url, headers, query, body, timeout, retry, extract}],
    "steps": [{api_id, inputs}],
    "variables": {...}
  }
  ```
- **param_perms**：参数级权限（`[{paramPath, userEditable}]`），控制普通用户能否编辑某参数
- **validate**：校验 steps 引用的 api_id 都在 apis 中（不真实调用，仅结构校验）
- 执行时由 `runs/target_client.py` 按 chain_json 编排 HTTP 请求

## TODO
- [ ] 模板版本管理
- [ ] 模板导入/导出
- [ ] chain_json 可视化编辑器（前端）
- [ ] 模板测试（单步调试）

## 协作守则
- `chain_json` 结构变更需同步 `target_client.py`（执行逻辑）。
- `param_perms` 是参数级权限，前端按此控制输入框可编辑性。

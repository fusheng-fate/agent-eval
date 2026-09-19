# configs 模块

## 职责
配置中心（P16/P21）：列表、读、改。按 `editable_by` 权限控制（admin / user）。区分全局配置和个人级配置。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/configs` | 登录用户 | 配置列表（含 effective value） |
| GET | `/api/configs/{key}` | 登录用户 | 读单个配置 |
| PUT | `/api/configs/{key}` | 按 editable_by | 改配置（admin 改全局，user 改个人级） |

## 文件
- `routes.py` — 路由（3 接口）
- `schemas.py` — ConfigOut / ConfigUpdateReq

## 依赖
- `app.core.database` — get_db
- `app.core.deps` — get_current_user
- `app.models.Config` / `app.models.UserConfig`

## 数据模型
- `Config`（`app/models/config_model.py`）：config_key / config_value(JSON) / scope(global|personal) / editable_by(admin|user) / description / updated_by
- `UserConfig`（`app/models/config_model.py`）：user_id / config_key / config_value(JSON) —— 个人级覆盖

## 权限
- 读：所有登录用户
- 改：
  - `editable_by=admin`：仅 admin 可改（改全局 Config）
  - `editable_by=user` 且 `scope=personal`：普通用户可改（改个人级 UserConfig）
  - 其他：403

## 关键概念
- **effective value**：personal 覆盖优先（UserConfig > Config）
- **个人级判定**：`scope=personal`（当前无个人级配置项，全部 admin 可改）
- **config_value 是 JSON**：`{"value": ...}` 结构，前端传 dict 或标量（标量自动包成 `{"value": ...}`）
- **启动时 seed**：`main.py` 的 `_seed_configs` 写入默认配置（幂等）

## 默认配置项
| key | scope | editable_by | 说明 |
|-----|-------|-------------|------|
| llm.base_url | global | admin | LLM 服务地址 |
| llm.api_key | global | admin | LLM API Key |
| llm.model | global | admin | 模型名字 |
| llm.max_tokens | global | admin | 最大 token |
| llm.timeout | global | admin | 超时(秒) |
| llm.auth | global | admin | LLM 认证方式（JSON：static/dynamic，dynamic 取 token 写回 llm.api_key） |
| target.endpoint | global | admin | 被测 Agent 地址 |
| concurrency.model | global | admin | 模型并发上限 |
| report.pass_threshold | global | admin | 通过阈值 |

> 注：被测 Agent 并发上限不再走 configs，已与流程模板绑定（`flow_templates.target_concurrency`，见 flow_templates 模块）。
| evaluator.extra_metric_limit | global | admin | 额外指标数量上限（Q3，默认 5） |

## TODO
- [ ] 配置变更审计日志（谁改的、改了什么、何时）
- [ ] 配置热更新通知（当前改完即生效，worker 下次读取）
- [ ] 配置校验（如 concurrency 必须是正整数）

## 协作守则
- 新增配置项需在 `main.py` 的 `_seed_configs` 加默认值。
- 个人级配置（`scope=personal`）普通用户可改；当前无个人级配置项，全部 admin。
- config_value 是 JSON，前端读写时注意 `{"value": ...}` 包装。

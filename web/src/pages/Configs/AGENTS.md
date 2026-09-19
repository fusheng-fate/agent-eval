# Configs 页面（配置中心）

## 职责
配置中心（v3.0 第 7 步）：LLM（含模型并发）/ 被测 / 阈值 / 流程模板（含被测 Agent 并发）/ 用户管理，按权限显隐编辑。

## 路由
`/configs`

## 消费接口
| 函数 | 接口 | 说明 |
|------|------|------|
| `configs.list` | GET `/configs` | 配置列表（含 effective value + editable 标记） |
| `configs.get` | GET `/configs/{key}` | 读单个 |
| `configs.update` | PUT `/configs/{key}` | 改配置（按 editable_by） |
| `flowTemplates.list` | GET `/flow-templates` | 流程模板列表 |
| `flowTemplates.create` | POST `/flow-templates` | 新建模板（admin） |
| `flowTemplates.update` | PUT `/flow-templates/{id}` | 更新模板（admin） |
| `flowTemplates.delete` | DELETE `/flow-templates/{id}` | 删除模板（admin） |
| `users.list` | GET `/users` | 用户列表（admin） |
| `users.create` | POST `/users` | 注册用户（admin） |
| `users.changePassword` | PUT `/users/{id}/password` | 改用户密码（admin） |
| `users.deactivate` | DELETE `/users/{id}` | 停用用户（admin） |

## 布局（页签式）
- **裁判模型配置** TAB：base_url / api_key / model / max_tokens / timeout / 模型并发上限（concurrency.model）
- **阈值配置** TAB：report.pass_threshold
- **流程模板** TAB：模板列表 + 新建/编辑/删除（admin）；模板对话框含「被测 Agent 并发上限」（target_concurrency，与模板绑定）
- **用户管理** TAB（仅 admin 可见）：用户列表 + 注册/改密/停用

## 权限（关键）
- **admin**：所有配置可编辑 + 流程模板增删改 + 用户管理 TAB 可见
- **普通用户**：
  - 所有配置只读
  - 流程模板只读（可见不可改）
  - 用户管理 TAB 隐藏
- 编辑按钮按 `config.editable_by` + `user.role` 显隐

## 关键交互
- 配置项：label + 输入框 + 说明，编辑态显示输入框，只读态显示值
- 保存：调 `configs.update`，成功提示
- 流程模板：chain_json 编辑（JSON 编辑器或可视化，骨架用 JSON textarea）
- 用户管理：注册表单（username/password/display_name）+ 操作按钮

## TODO
- [ ] 配置变更审计日志展示
- [ ] chain_json 可视化编辑器
- [ ] 用户列表分页
- [ ] 配置分组折叠

## 协作守则
- 权限显隐是核心：每个配置项的 editable 状态从后端 `configs.list` 返回，前端据此渲染。
- 被测 Agent 并发上限在流程模板对话框编辑（非配置中心），随模板保存。
- 用户管理 TAB 整体按 role 显隐（非逐项）。

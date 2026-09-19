# TaskCenter 页面（任务中心）

## 职责
任务中心（v3.0 第 2.1 步，登录后默认落点）：顶部看板 + 任务列表 + 按权限操作。

## 路由
`/`（默认）

## 消费接口
| 函数 | 接口 | 说明 |
|------|------|------|
| `dashboard.summary` | GET `/dashboard/summary` | 看板（累计用例/通过/失败/通过率/任务数/token/延迟） |
| `runs.list` | GET `/runs` | 任务列表（可按 status/owner/keyword 筛选） |
| `runs.pause` | POST `/runs/{id}/pause` | 暂停（owner-or-admin） |
| `runs.resume` | POST `/runs/{id}/resume` | 继续（owner-or-admin） |
| `runs.stop` | POST `/runs/{id}/stop` | 停止（owner-or-admin） |
| `runs.delete` | DELETE `/runs/{id}` | 删除（owner-or-admin，进行中禁用） |

## 布局
- **顶部看板**：KPI 卡片（总用例/通过/失败/通过率/进行中任务）
- **任务列表**：表格（任务名/状态/进度/创建时间/操作），支持筛选（状态/我的/搜索）
- **操作按钮**：按 `user.role` + `run.owner_id` 显隐
  - 进行中：暂停/停止
  - 已暂停：继续
  - 非进行中：删除
  - 普通用户仅自己的任务可操作，他人任务只读
  - admin 可操作所有任务

## 状态
- 看板：页面加载时拉一次（或定时刷新）
- 列表：筛选条件变化时重新拉取
- 进度：列表页显示 done/total，实时性靠用户手动刷新或轮询

## 组件
- KPI 卡片（白底 16px 圆角，hover 阴影）
- 任务表格（1px `#DCE0E6` 边框，行 hover 浅底）
- 状态徽章（pending 灰 / running 蓝 / paused 橙 / done 绿 / stopped 灰 / error 红）
- 操作按钮组

## 权限
- 看板/列表：所有登录用户
- 操作：owner-or-admin

## TODO
- [ ] 任务进度实时刷新（轮询或 SSE）
- [ ] 新建任务入口（跳 /execution）
- [ ] 任务列表分页

## 协作守则
- 看板数据是全局累计（非单任务），注意区分。
- 操作按钮的显隐逻辑要覆盖所有状态 × 角色 × owner 组合。

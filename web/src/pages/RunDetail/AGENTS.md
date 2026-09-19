# RunDetail 页面（任务详情）

## 职责
任务详情（v3.0 第 2.2 步）：单任务的过程视图，统计条 + 逐用例网格 + 按权限暂停/继续/停止 + 导出。

## 路由
`/runs/:id`

## 消费接口
| 函数 | 接口 | 说明 |
|------|------|------|
| `runs.get` | GET `/runs/{id}` | 任务详情（含进度/分数） |
| `runs.cases` | GET `/runs/{id}/cases` | 逐用例结果分页（page/size） |
| `runs.pause` | POST `/runs/{id}/pause` | 暂停（owner-or-admin） |
| `runs.resume` | POST `/runs/{id}/resume` | 继续（owner-or-admin） |
| `runs.stop` | POST `/runs/{id}/stop` | 停止（owner-or-admin） |
| `runs.export` | GET `/runs/{id}/export?level=exec\|eval` | 导出 Excel |

## 布局
- **顶部统计条**：任务名/状态/进度（done/total）/通过率/主分/操作按钮
- **逐用例网格**：表格（用例编号/状态/主分/标准指标分/额外指标分/简短评价），点击行跳单用例详情
- **导出**：exec（+执行结果列）/ eval（+评测得分+简短评价列）

## 状态
- 详情：页面加载拉一次
- 进度：**轮询** `GET /runs/{id}`（2s），running/paused 时持续，done/stopped/error 停止轮询
- 用例列表：分页加载，状态变化时刷新当前页

## 组件
- 统计条（KPI + 操作按钮）
- 用例表格（可展开行显示指标明细）
- 状态徽章
- 进度条（done/total）

## 权限
- 读：所有登录用户
- 操作：owner-or-admin
- 导出：所有登录用户

## TODO
- [ ] SSE 实时进度（替代轮询）
- [ ] 用例筛选（按状态/分数区间）
- [ ] 用例排序（按分数/编号）
- [ ] 虚拟滚动（大结果集）

## 协作守则
- 轮询要在组件卸载时清理（useEffect return）。
- 用例行点击跳 `/runs/:id/cases/:caseId`。
- 导出走 `apiDownload`（blob 下载）。

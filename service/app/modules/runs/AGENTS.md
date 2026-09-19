# runs 模块（核心）

## 职责
任务执行：创建（单用户单活跃任务 P25）、列表、详情、逐用例、暂停/继续/停止、删除、导出、自检、看板。含执行 worker（队列消费 + LLM/被测调用 + 评分 + 落库）。

**这是最复杂的模块**，含 worker 线程、Redis 队列、LLM 调用、被测 Agent 调用、Excel 导出、看板聚合。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/runs` | 登录用户 | 创建任务（P25：已有活跃任务则 409） |
| GET | `/api/runs` | 登录用户 | 列表（可按 status/owner/keyword 筛选） |
| GET | `/api/runs/{id}` | 登录用户 | 详情 |
| GET | `/api/runs/{id}/cases` | 登录用户 | 逐用例结果分页 |
| GET | `/api/runs/{id}/cases/{case_id}` | 登录用户 | 单条用例结果 |
| POST | `/api/runs/{id}/pause` | owner-or-admin | 暂停 |
| POST | `/api/runs/{id}/resume` | owner-or-admin | 继续（重新入队未完成 case） |
| POST | `/api/runs/{id}/stop` | owner-or-admin | 停止 |
| DELETE | `/api/runs/{id}` | **仅管理员**（Q2） | 删除（进行中 409；普通用户不可删） |
| GET | `/api/runs/{id}/export` | 登录用户 | 导出 Excel（level=exec\|eval） |
| POST | `/api/runs/selfcheck/exec` | 登录用户 | 执行自检（取首用例真实调被测 Agent） |
| POST | `/api/runs/selfcheck/eval` | 登录用户 | 评测自检（测 LLM 接口） |
| GET | `/api/dashboard/summary` | 登录用户 | 看板（累计指标聚合，P3；Q5：可按时间/用户筛选，默认全局） |

## 文件
- `routes.py` — 路由（13 接口 + dashboard_router）
- `schemas.py` — RunCreateReq / RunOut / CaseResultOut / DashboardSummary
- `worker.py` — 执行 worker（process_case / start_workers / _worker_loop）
- `task_queue.py` — PG 队列（claim_case / recover_stale_running / pending_count）
- `llm_client.py` — LLM 评测调用（build_score_prompt / call_llm / score_metric）
- `target_client.py` — 被测 Agent 调用（call_target 单轮 / call_target_multi_turn 多轮拆分拼接 / split_user_input）
- `export_service.py` — Excel 导出（export_run_excel）

## 依赖
- `app.core.config` — settings（CONCURRENCY_MODEL / CONCURRENCY_TARGET / PASS_THRESHOLD / WORKER_COUNT / WORKER_CLAIM_POLL_SEC / STALE_RUNNING_MAX_AGE_SEC）
- `app.core.database` — get_db / SessionLocal
- `app.core.redis_client` — get_redis（仅用于限流计数，队列已改 PG）
- `app.core.deps` — get_current_user / require_admin / require_owner_or_admin
- `app.models` — Run / CaseResult / Case / Dataset / FlowTemplate / Evaluator / EvaluatorMetric / Metric / Config
- `app.modules.reports.report_service` — build_report（run 完成后跨模块调用）

## 数据模型
- `Run`（`app/models/run.py`）：task_name / owner_id / evaluator_id / dataset_id / flow_template_id / extra_metric_ids / status / total_cases / done_cases / passed_cases / failed_cases / overall_score / model_concurrency / target_concurrency / started_at / finished_at / created_at
- `CaseResult`（`app/models/run.py`）：run_id / case_id / status / overall_score / standard_metrics / extra_metrics / brief_comment / agent_output / token_usage / latency_sec / error_msg / attempt / finished_at

## 权限
- 创建/读：所有登录用户
- 暂停/继续/停止：owner-or-admin（普通用户仅自己的，管理员全部）
- **删除：仅管理员**（Q2 已定：普通用户不能删除任务/报告，仅可暂停/继续/停止）
- 看板：所有登录用户

## 关键概念
- **任务状态机**：pending → running → paused → running → done / stopped / error
- **单用户单活跃任务**（P25）：创建时该用户已有 pending/running/paused 任务则 409
- **PG 队列**：`case_results` 表 `status='pending'` 即队列。`create_run` 批量 INSERT pending 行（不再逐条入队 Redis）；worker 用 `claim_case`（PG `FOR UPDATE SKIP LOCKED`，SQLite 退化）原子抢任务
- **断点续跑**：worker 直接抢 pending 行，重启后天然续跑；崩溃遗留的 `running` 态由 `recover_stale_running`（locked_at 超时）回 pending；已完成 case（passed/failed/error）不重跑
- **暂停**：`claim_case` 子查询只抢 `run.status='running'` 的 case，paused run 的 pending 不被抢；恢复时把崩溃遗留 running 回 pending 即自动续跑
- **停止**：run.status=stopped 时 claim 不抢该 run 的 case；已 claim 到的 case 在 process_case 检测到 stopped 置 skipped（终态），paused 才回 pending
- **并发限流**（P21）：模型并发 / 待测系统并发用 Redis 计数信号量（上限来自 configs），`_acquire_limit` 带超时（防 LLM/被测卡死时 worker 无限忙等）
- **评分**：标准指标（加权）+ 额外指标（单独）→ overallScore = Σ(标准指标分 × weight)，指标分与主分均为百分制 0-100，passed = overallScore >= 阈值（默认 80，配置中心 `report.pass_threshold`）
- **额外指标约束**（Q3/Q4）：创建时校验——数量 ≤ `report.extra_metric_max`（默认 5，管理员可调）；且每个额外指标须为指标库中存在、**标准评估器未引用**的指标
- **看板筛选**（Q5）：`GET /api/dashboard/summary` 支持 `since`/`until`/`owner`（`mine`/UUID/缺省全局）
- **报告触发**：run.done_cases >= total_cases 时调 `reports.build_report`（代码聚合）

## worker 执行流程
- `_worker_loop(worker_id)`：循环 `task_queue.claim_case(worker_id)` 抢 pending case（PG `FOR UPDATE SKIP LOCKED`），无任务短轮询 `WORKER_CLAIM_POLL_SEC`
- `process_case(cr_id)`：
  1. 取 case_result（claim 已置 running）→ 取 run，检查状态（paused/stopped/error 回 pending 不执行）
  2. 取 case
  3. 调被测 Agent（target_client.call_target_multi_turn，多轮拆分 + 每轮独立调用 + 拼接汇总，Redis 限流带超时）
  4. 评分：标准指标（加权）+ 额外指标（单独），每个指标调 LLM（Redis 限流带超时）
  5. 计算 overallScore，更新 case_result
  6. 更新 run 计数，完成时 SQL 聚合均分 + 触发报告

## 测试
- `tests/test_runs_reports.py`（在 `dev/service/tests/`）：评分数学 / 报告聚合 / HTML 渲染 / 被测调用 / LLM 解析。
- 跑法：`.venv/Scripts/python -m pytest tests/ -q`（内存 SQLite + 假 Redis，无需 PG/Redis）。

## TODO
- [x] 执行自检真实调被测 Agent（已实现：取首用例调 call_target）
- [x] token_usage / latency_sec 真实采集（llm_client 已采，worker 汇总落库）
- [ ] 限流改令牌桶（当前简化 Redis 计数）
- [ ] SSE `GET /api/runs/{id}/events`（当前前端轮询）
- [ ] worker 水平扩展（多容器，当前单副本线程池）
- [ ] LLM 调用重试（当前失败直接 error）

## 协作守则
- **worker 是后台线程**，改 worker.py 需重启服务生效。
- **跨模块调用**：worker 完成后调 `reports.build_report`，是唯一跨模块依赖，改 reports 接口需同步。
- **PG 队列**：队列 = `case_results.status='pending'`，多副本共享同一张表，`FOR UPDATE SKIP LOCKED` 互斥抢锁，无需 Redis 队列。
- **崩溃回收**：`recover_stale_running`（启动时跑）把 `locked_at` 超过 `STALE_RUNNING_MAX_AGE_SEC` 的 running 行回 pending。
- **限流 key**：`agent_eval:limit:model` / `agent_eval:limit:target`（Redis 计数），生产建议加 TTL 防泄漏。

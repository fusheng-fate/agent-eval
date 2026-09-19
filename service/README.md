# Agent 评测平台 · 服务化后端（骨架）

单后端（合并原 :8002 评估器 + :8003 执行），FastAPI + PostgreSQL + Redis。
纯 HTTP 执行（无子进程/无 skill/无共享磁盘），任务队列 + worker 池，支持暂停/继续/停止 + 断点续跑。

依据：`docs/服务化产品决策.md`、`docs/服务化数据模型与接口.md`。

## 目录结构

```
service/
├── app/
│   ├── main.py              # 应用工厂 + 生命周期(建表/引导/起worker)
│   ├── schemas.py           # Pydantic 请求/响应模型
│   ├── core/
│   │   ├── config.py        # 环境变量配置
│   │   ├── database.py      # SQLAlchemy 引擎/会话
│   │   ├── redis_client.py  # Redis 客户端
│   │   ├── security.py      # JWT + 密码哈希
│   │   └── deps.py          # 当前用户/管理员/owner-or-admin 依赖
│   ├── models/              # SQLAlchemy ORM 模型(对应 PG 表)
│   ├── routers/             # 路由: auth/users/metrics/evaluators/datasets/flow_templates/runs/reports/configs/dashboard
│   └── services/
│       ├── bootstrap.py     # 建表 + 内置管理员 + 标准评估器 + 默认配置
│       ├── task_queue.py    # PG 队列(claim_case / recover_stale_running)
│       ├── worker.py        # worker 池(限流/断点续跑/暂停停止)
│       ├── llm_client.py    # 拼 prompt 调 LLM 评分
│       ├── target_client.py # 调被测 Agent API(chain 编排)
│       ├── report_service.py# 代码聚合报告 + HTML 导出
│       └── export_service.py# 结果 Excel 导出
├── requirements.txt
├── Dockerfile
└── docker-compose.yml       # postgres + redis + api
```

## 本地启动

```bash
cd dev/service
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
# 或 .venv/bin/pip install -r requirements.txt                          # Linux/mac
# 需先启动 PostgreSQL 与 Redis（或用 docker compose）
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动时自动：建表 → 内置管理员(`admin`/`admin123`) → 内置标准评估器 → 写入默认配置 → 起 worker。

## 容器化启动

```bash
cd dev/service
docker compose up -d
# 访问 http://localhost:8000/docs
```

## 接口

33 个接口，见 `docs/服务化数据模型与接口.md` 第二节。Swagger：`/docs`。

## 关键行为

- **单用户单活跃任务**（P25）：`POST /runs` 时该用户已有 pending/running/paused 任务则 409。
- **断点续跑**：worker 重启把 running 任务的未完成 case 重新入队；已完成 case 不重跑。
- **暂停/继续/停止**：`POST /runs/{id}/pause|resume|stop`，按 owner-or-admin 权限。
- **评分**：标准评估器指标加权（Σweight=1，阈值 4）→ 主分；额外指标单独计分不进主分。
- **报告**：run 全部完成后代码聚合 → `reports` 表；`GET /reports/{id}/export.html` 导出。
- **导出**：`GET /runs/{id}/export?level=exec|eval`（原 Excel 列 + 执行结果列 [+ 评测得分/评价列]）。

## 残留问题排查（改代码后"修复不生效"）

worker 是进程内线程，**杀不掉旧 worker 线程就会持续写脏数据**。改完代码后若发现
"修复没生效 / case 莫名 error / 任务卡住"，按以下顺序排查：

1. **杀所有 python 进程**（含 uvicorn 父进程 + worker 子进程，它们是两个 PID）：
   ```bash
   taskkill //F //IM python.exe        # Windows
   pkill -f uvicorn                    # Linux
   ```
   只杀监听端口的那个进程不够——uvicorn 的 worker 子进程是独立 PID，必须全杀。

2. **清 `__pycache__`**：`.pyc` 字节码缓存可能比 `.py` 旧，导致加载旧代码。
   ```bash
   find . -type d -name __pycache__ -exec rm -rf {} +
   ```

3. **清 Redis 限流计数**：`agent_eval:limit:*`（`:count`/`:bucket`）残留会让新 worker
   误判槽位已满，case 卡在"等待并发槽位超时"。
   ```bash
   redis-cli -h <host> -p <port> -n <db> -a <pass> --scan --pattern 'agent_eval:limit:*' | xargs redis-cli -h <host> -p <port> -n <db> -a <pass> DEL
   ```

4. **重置残留 case_results**：旧 worker 崩溃遗留的 `running`/`error`（无 `finished_at`）
   行会卡住任务。启动时 `recover_stale_running` 会自动回收（含 error 残留），但若
   不想等 10min 超时，可手动：
   ```sql
   UPDATE case_results SET status='pending', locked_by=NULL, locked_at=NULL
   WHERE status IN ('running','error') AND finished_at IS NULL;
   ```

5. **重启服务**：`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
   （注意 `--host 127.0.0.1`：若 0.0.0.0:8000 有僵尸 socket 占着，用 127.0.0.1 可共存）。

> 判断"残留旧进程"的特征：case 的 `locked_at` **早于** `created_at`（锁时间早于创建时间），
> 或 `error_msg` 无 traceback（旧格式）。当前代码的 error_msg 必带 traceback。

## 骨架 TODO（未实现，需补）

- worker 的 `_trigger_report` 已接 `report_service.build_report`，但 LLM/被测 Agent 真实调用需配置后验证。
- 执行自检 `selfcheck/exec` 仅校验模板，未真实调被测 Agent。
- 限流用简化 Redis 计数，生产建议令牌桶。
- 建表用 `create_all`，生产建议 Alembic 迁移。
- 进度实时推送（SSE `GET /runs/{id}/events`）未实现，当前前端轮询 `GET /runs/{id}`。

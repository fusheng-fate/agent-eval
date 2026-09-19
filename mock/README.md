# Mock 被测智能体服务

独立 FastAPI 服务，用 LLM 模拟待测 Agent 的多轮对话，供评测平台作为 target 联调/演示。
不依赖 PG / Redis，会话存进程内 dict。

## 启动

```bash
cd dev/mock
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
cp .env.example .env   # 填入 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
.venv/Scripts/python main.py
# 或
.venv/Scripts/python -m uvicorn app:app --host 0.0.0.0 --port 8100
```

默认端口 `8100`，Swagger 文档 `http://localhost:8100/docs`。

## 三个接口

### 1. 建会话 `POST /mock/session`（JSON 请求）

```bash
curl -X POST http://localhost:8100/mock/session \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "demo"}'
```

响应：

```json
{ "session_id": "3f2c...", "agent_name": "demo" }
```

### 2. 对话 `POST /mock/chat`（urlencode 表单请求）

请求体为 `application/x-www-form-urlencoded`，字段：`session_id`、`message`（用户输入）、`user`（可选，默认 `user`）。

```bash
curl -X POST http://localhost:8100/mock/chat \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "session_id=3f2c..." \
  --data-urlencode "message=你好，请介绍一下你自己"
```

响应（`data` 字段就是「响应里包含的那个 JSON 字符串」）：

```json
{
  "session_id": "3f2c...",
  "text": "我是模拟智能体……{\"answer\": \"...\", \"confidence\": 0.9, \"sources\": []}",
  "data": "{\"answer\": \"...\", \"confidence\": 0.9, \"sources\": []}",
  "turn": 1
}
```

### 3. 解析 `POST /mock/parse`（JSON 请求）

把上一步 `data` 里的 JSON 字符串作为 `payload` 传入，提取并组装有效信息。

```bash
curl -X POST http://localhost:8100/mock/parse \
  -H "Content-Type: application/json" \
  -d '{"payload": "{\"answer\": \"...\", \"confidence\": 0.9, \"sources\": []}", "session_id": "3f2c..."}'
```

响应：

```json
{
  "session_id": "3f2c...",
  "answer": "...",
  "confidence": 0.9,
  "sources": [],
  "raw": { "answer": "...", "confidence": 0.9, "sources": [] }
}
```

## 典型调用链（评测平台侧）

```
POST /mock/session  → 拿 session_id
POST /mock/chat     → 拿 data(JSON 字符串)
POST /mock/parse    → 拿结构化 answer/confidence/sources
```

评测平台的流程模板（`chain_json`）可编排这三步：第 1 步 `extract` 出 `session_id`，
第 2 步 `extract` 出 `data`，第 3 步把 `data` 作为输入解析出最终答案。

## 配置（环境变量，见 `.env.example`）

| 变量 | 说明 | 默认 |
|------|------|------|
| `MOCK_PORT` | 服务端口 | `8100` |
| `LLM_BASE_URL` | LLM 服务地址（OpenAI 兼容） | 空（必填） |
| `LLM_API_KEY` | LLM API Key | 空 |
| `LLM_MODEL` | 模型名 | 空（必填） |
| `SESSION_TTL_SECONDS` | 会话闲置过期秒数 | `3600` |
| `SESSION_MAX_TURNS` | 单会话最多保留轮数 | `50` |
| `AGENT_SYSTEM_PROMPT` | 模拟智能体人设提示词 | 见 `config.py` |

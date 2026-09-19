"""Mock 被测智能体服务（独立 FastAPI 应用）。

三个接口（模拟待测 Agent 的对话流程）：
  1. POST /mock/session  建会话，返回 sessionId（JSON 请求）
  2. POST /mock/chat     对话，请求体为 urlencode 表单（sessionId + 用户输入），
                         调 LLM 后返回「包含一个 JSON 字符串」的响应
  3. POST /mock/parse    解析，JSON 请求（含上一步响应里的 JSON 字符串），
                         提取并组装其中有效信息
"""
import json
import logging
from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import mock_settings
from .llm_client import call_llm, extract_json, _build_messages
from . import session_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mock")


# ---------------- 请求/响应模型 ----------------

class SessionCreateReq(BaseModel):
    """建会话请求（JSON）。可携带初始上下文，便于预置人设/变量。"""
    agent_name: str | None = None
    initial_context: dict[str, Any] = Field(default_factory=dict)


class SessionCreateResp(BaseModel):
    session_id: str
    agent_name: str = "mock-agent"


class ParseReq(BaseModel):
    """解析请求（JSON）。payload 为 chat 响应里那个 JSON 字符串。"""
    payload: str
    session_id: str | None = None


class ParseResp(BaseModel):
    session_id: str | None = None
    answer: str = ""
    confidence: float = 0.0
    sources: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


# ---------------- 应用工厂 ----------------

def create_app() -> FastAPI:
    app = FastAPI(title="mock-agent-service", lifespan=None)
    origins = [o.strip() for o in mock_settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 1) 建会话
    @app.post("/mock/session", response_model=SessionCreateResp)
    def create_session(req: SessionCreateReq):
        sid = session_store.create_session()
        return SessionCreateResp(session_id=sid, agent_name=req.agent_name or "mock-agent")

    # 2) 对话（urlencode 表单）→ 返回含 JSON 字符串的响应
    @app.post("/mock/chat")
    def chat(
        session_id: str = Form(...),
        message: str = Form(...),
        user: str = Form(default="user"),
    ):
        history = session_store.get_history(session_id)
        if history is None:
            raise HTTPException(404, "会话不存在或已过期，请先调用 /mock/session")
        try:
            raw_reply = call_llm(_build_messages(history, message))
        except Exception as exc:  # LLM 调用失败
            log.exception("LLM 调用失败")
            raise HTTPException(502, f"LLM 调用失败: {exc}") from exc

        # 把回复里的 JSON 对象单独拿出来，作为「JSON 字符串」字段返回
        embedded = extract_json(raw_reply)
        json_str = json.dumps(embedded, ensure_ascii=False)
        session_store.append_turn(session_id, message, raw_reply)
        return {
            "session_id": session_id,
            "text": raw_reply,          # LLM 完整回复（自然语言）
            "data": json_str,           # 响应里包含的 JSON 字符串（待 parse 提取）
            "turn": len(history) // 2 + 1,
        }

    # 3) 解析（JSON 请求）→ 提取组装有效信息
    @app.post("/mock/parse", response_model=ParseResp)
    def parse(req: ParseReq):
        obj = extract_json(req.payload)
        answer = obj.get("answer", "")
        confidence = obj.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        sources = obj.get("sources", [])
        if not isinstance(sources, list):
            sources = [str(sources)] if sources else []
        return ParseResp(
            session_id=req.session_id,
            answer=str(answer),
            confidence=confidence,
            sources=[str(s) for s in sources],
            raw=obj,
        )

    @app.get("/mock/health")
    def health():
        return {
            "status": "ok",
            "sessions": session_store.session_count(),
            "llm_configured": bool(mock_settings.LLM_BASE_URL and mock_settings.LLM_MODEL),
        }

    return app


app = create_app()

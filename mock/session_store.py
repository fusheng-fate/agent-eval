"""会话存储（进程内 dict，多轮对话上下文）。

mock 场景够用：无需 PG/Redis，重启丢失可接受。
带 TTL 过期 + 单会话轮数上限，防内存膨胀。
"""
import threading
import time
import uuid
from typing import Any

from .config import mock_settings

_lock = threading.Lock()
# sessionId -> {"created": ts, "last_active": ts, "history": [{"role","content"}, ...]}
_sessions: dict[str, dict[str, Any]] = {}


def create_session() -> str:
    now = time.time()
    sid = uuid.uuid4().hex
    with _lock:
        _gc_locked(now)
        _sessions[sid] = {"created": now, "last_active": now, "history": []}
    return sid


def get_history(session_id: str) -> list[dict[str, str]] | None:
    """返回会话历史；会话不存在/已过期返回 None。"""
    now = time.time()
    with _lock:
        _gc_locked(now)
        sess = _sessions.get(session_id)
        if sess is None:
            return None
        sess["last_active"] = now
        return list(sess["history"])


def append_turn(session_id: str, user_input: str, assistant_output: str) -> None:
    now = time.time()
    with _lock:
        sess = _sessions.get(session_id)
        if sess is None:
            return
        sess["history"].append({"role": "user", "content": user_input})
        sess["history"].append({"role": "assistant", "content": assistant_output})
        # 轮数上限：只保留最近 N 轮（每轮 = user+assistant 两条）
        max_msgs = mock_settings.SESSION_MAX_TURNS * 2
        if len(sess["history"]) > max_msgs:
            sess["history"] = sess["history"][-max_msgs:]
        sess["last_active"] = now


def _gc_locked(now: float) -> None:
    """清理过期会话（调用方需持锁）。"""
    ttl = mock_settings.SESSION_TTL_SECONDS
    expired = [sid for sid, s in _sessions.items() if now - s["last_active"] > ttl]
    for sid in expired:
        _sessions.pop(sid, None)


def session_count() -> int:
    with _lock:
        return len(_sessions)

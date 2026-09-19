"""LLM 调用（OpenAI 兼容 /chat/completions）+ 提示词构造。

用于模拟待测智能体：把会话历史 + 当前输入拼成 messages，调 LLM 拿回复。
"""
import json
import logging
from typing import Any

import httpx

from .config import mock_settings

log = logging.getLogger("mock.llm")


def _build_messages(history: list[dict[str, str]], user_input: str) -> list[dict[str, str]]:
    """system 人设 + 历史 + 当前输入。"""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": mock_settings.AGENT_SYSTEM_PROMPT}
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})
    return messages


def call_llm(messages: list[dict[str, str]]) -> str:
    """调 LLM，返回 assistant 的文本回复。失败抛异常。"""
    base_url = (mock_settings.LLM_BASE_URL or "").rstrip("/")
    if not base_url:
        raise RuntimeError("LLM_BASE_URL 未配置")
    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if mock_settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {mock_settings.LLM_API_KEY}"
    body = {
        "model": mock_settings.LLM_MODEL,
        "max_tokens": mock_settings.LLM_MAX_TOKENS,
        "messages": messages,
        "temperature": 0.3,
    }
    with httpx.Client(timeout=mock_settings.LLM_TIMEOUT) as client:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def extract_json(text: str) -> dict[str, Any]:
    """从 LLM 回复文本中提取嵌入的 JSON 对象（容错：剥 markdown 代码块 / 抓首个 {...}）。"""
    text = (text or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"data": obj}
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                return obj if isinstance(obj, dict) else {"data": obj}
            except json.JSONDecodeError:
                return {}
        return {}

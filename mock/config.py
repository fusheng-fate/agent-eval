"""Mock 服务配置（环境变量驱动）。

独立服务，端口/LLM 地址等全部走环境变量，便于单独起停与容器化。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MockSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 服务 ----
    MOCK_HOST: str = "0.0.0.0"
    MOCK_PORT: int = 8100
    CORS_ORIGINS: str = "*"

    # ---- 被模拟的 LLM（OpenAI 兼容 /chat/completions）----
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT: int = 120

    # ---- 会话 ----
    SESSION_TTL_SECONDS: int = 3600  # 会话闲置过期时间
    SESSION_MAX_TURNS: int = 50  # 单会话最多保留轮数，防内存膨胀

    # ---- 模拟智能体人设（简单提示词，可被环境变量覆盖）----
    AGENT_SYSTEM_PROMPT: str = (
        "你是一个模拟的待测智能体，用于评测平台的联调与演示。"
        "请根据用户输入给出准确、简洁的回复。"
        "你每次的回复都必须包含一个 JSON 对象，该 JSON 至少包含字段："
        "answer（字符串，你的核心回答）、confidence（0-1 的浮点数，你对答案的把握）、"
        "sources（字符串数组，你参考的依据，可为空）。"
        "JSON 对象要嵌在你的回复文本中，前后可以有少量说明文字。"
    )


@lru_cache
def get_mock_settings() -> MockSettings:
    return MockSettings()


mock_settings = get_mock_settings()

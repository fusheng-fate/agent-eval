"""全局配置（环境变量驱动，无写死端口/路径）。

服务化原则：所有外部依赖（PG / Redis / LLM / 初始管理员）都走环境变量，
容器化部署时由编排层注入。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 服务 ----
    APP_NAME: str = "agent-eval-platform"
    API_PREFIX: str = "/api"
    SERVICE_HOST: str = "0.0.0.0"
    SERVICE_PORT: int = 8000
    CORS_ORIGINS: str = "*"  # 逗号分隔；生产应限定

    # ---- 前端静态托管（方案 B：后端顺带 serve dist）----
    FRONTEND_DIR: str = "web"  # 前端构建产物目录（镜像内相对 WORKDIR）

    # ---- PostgreSQL ----
    PG_HOST: str = "127.0.0.1"
    PG_PORT: int = 5432
    PG_USER: str = "postgres"
    PG_PASSWORD: str = "postgres"
    PG_DB: str = "agent_eval"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.PG_USER}:{self.PG_PASSWORD}"
            f"@{self.PG_HOST}:{self.PG_PORT}/{self.PG_DB}"
        )

    # ---- Redis（任务队列 / 分布式锁 / 限流计数）----
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ---- 认证 ----
    JWT_SECRET: str = "change-me-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 12  # 12h，access token
    JWT_REFRESH_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7d，refresh token

    # 初始管理员（P23：定死一个管理账号密码，首次部署内置）
    BOOTSTRAP_ADMIN_USERNAME: str = "admin"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin123"
    BOOTSTRAP_ADMIN_DISPLAY: str = "系统管理员"

    # ---- LLM 评测模型（默认值，可被配置中心覆盖）----
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT: int = 120
    LLM_RETRY_COUNT: int = 3
    LLM_RETRY_BACKOFF: float = 3.0  # 重试间隔（秒）

    # ---- 被测 Agent（默认值，可被配置中心覆盖）----
    TARGET_ENDPOINT: str = ""
    TARGET_TIMEOUT: int = 60

    # ---- 并发上限（P21：管理员在配置中心设，这里是兜底默认）----
    CONCURRENCY_MODEL: int = 5
    CONCURRENCY_TARGET: int = 3

    # ---- 报告阈值（百分制 0-100）----
    PASS_THRESHOLD: float = 80.0

    # ---- 队列（PG case_results 表）----
    WORKER_COUNT: int = 12  # 执行池线程数（调被测 Agent，多副本靠多容器）
    # 注意：执行池线程数应 >= 单模板的最大 target_concurrency（默认 3，模板可设到 ≤10）。
    # 实际并发受 _acquire_limit 信号量（run.target_concurrency，按模板区分）控制，
    # 线程数略多无害：多余的线程在抢不到槽位时阻塞等待（非空转），不会死锁。
    # 若线程数 < 槽位数，则并发被线程数卡住、浪费被测 Agent 的可用并发。
    # 评分池线程数不再独立配置，直接取 CONCURRENCY_MODEL（LLM 并发上限），
    # 保证评分线程数 ≤ LLM 槽位数，避免结构性 SlotBusy。
    WORKER_CLAIM_POLL_SEC: float = 1.0  # 无任务时 worker 轮询间隔
    STALE_RUNNING_MAX_AGE_SEC: int = 600  # 崩溃回收阈值：running/scoring 态超过此时长回退
    STALE_RUNNING_RECOVER_INTERVAL_SEC: int = 60  # 周期性回收卡死 case 的间隔（兜底，防异常处理遗漏）


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

"""Redis 客户端（任务队列 / 分布式锁 / 限流计数）。

单节点起步，预留多节点：队列用 List（LPUSH/BRPOP），锁用 SETNX，限流用 INCR+EXPIRE。
"""
import redis

from .config import settings

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    return _redis


def health() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False

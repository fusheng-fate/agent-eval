"""JWT（access/refresh）+ 密码哈希 + 令牌黑名单。

- access token：短效（12h），承载请求鉴权；含 jti，可被登出加入黑名单吊销。
- refresh token：长效（7d），仅用于 `/auth/refresh` 换新 access，refresh 同步轮换。
"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

# 令牌类型，写入 payload 的 "type" 字段，防止 access/refresh 混用
ACCESS = "access"
REFRESH = "refresh"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _encode(user_id: str, username: str, role: str, token_type: str, expire_minutes: int) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expire_minutes)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": exp,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM), int(exp.timestamp())


def create_access_token(user_id: str, username: str, role: str) -> tuple[str, int]:
    """返回 (token, exp 时间戳)。"""
    return _encode(user_id, username, role, ACCESS, settings.JWT_EXPIRE_MINUTES)


def create_refresh_token(user_id: str, username: str, role: str) -> tuple[str, int]:
    return _encode(user_id, username, role, REFRESH, settings.JWT_REFRESH_EXPIRE_MINUTES)


def _decode(token: str, expected_type: str | None) -> dict | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if expected_type is not None and payload.get("type") != expected_type:
        return None
    return payload


def decode_access_token(token: str) -> dict | None:
    return _decode(token, ACCESS)


def decode_refresh_token(token: str) -> dict | None:
    return _decode(token, REFRESH)


def blacklist_jti(jti: str, exp: int) -> None:
    """把令牌 jti 加入 Redis 黑名单，TTL = 令牌剩余有效期。"""
    from .redis_client import get_redis

    ttl = max(int(exp) - int(datetime.now(timezone.utc).timestamp()), 1)
    get_redis().set(f"auth:blacklist:{jti}", "1", ex=ttl)


def is_jti_blacklisted(jti: str) -> bool:
    from .redis_client import get_redis

    try:
        return bool(get_redis().exists(f"auth:blacklist:{jti}"))
    except Exception:
        return False

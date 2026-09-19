"""测试夹具：内存 SQLite（JSONB/ARRAY 适配）+ 假 Redis。

不依赖 PostgreSQL / 真实 Redis，纯逻辑层可跑。
"""
import pytest
from sqlalchemy import Text, create_engine
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

# 让 SQLite 能建 JSONB / ARRAY 列（序列化为 TEXT，值本身是 Python 对象）
JSONB().compare_type = lambda *a, **k: Text


@compiles(ARRAY, "sqlite")
def _array_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


# ARRAY 在 SQLite 下以 JSON 文本存取：绑定 list→json，读取 json→list。
# 仅当方言是 SQLite 时启用，避免污染 PG 的 list 绑定（PG 原生支持 list→array）。
# 签名与 SQLAlchemy 内部调用一致：bind_processor(self, dialect) / result_processor(self, dialect, coltype)。
def _array_bind_processor(self, dialect):
    if dialect.name != "sqlite":
        return None
    import json
    return lambda v: json.dumps(v) if v is not None else None


def _array_result_processor(self, dialect, coltype=None):
    if dialect.name != "sqlite":
        return None
    import json
    return lambda v: json.loads(v) if v is not None else None


ARRAY.bind_processor = _array_bind_processor
ARRAY.result_processor = _array_result_processor


from app.core.database import Base  # noqa: E402
import app.models  # noqa: E402,F401  注册全部表


class FakeRedis:
    """最小 Redis 桩：限流计数恒放行；黑名单 set/exists 用内存 dict 模拟。"""

    def __init__(self):
        self._store = {}
        self._ttl = {}

    def incr(self, key):
        """INCR：key 不存在则从 0 开始累加，返回新值。"""
        cur = int(self._store.get(key, 0))
        cur += 1
        self._store[key] = str(cur)
        return cur

    def decr(self, key):
        """DECR：key 不存在则从 0 开始递减，返回新值。"""
        cur = int(self._store.get(key, 0))
        cur -= 1
        self._store[key] = str(cur)
        return cur

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, ex=None):
        self._store[key] = value
        if ex:
            self._ttl[key] = ex
        return True

    def setex(self, key, ttl, value):
        self._store[key] = value
        self._ttl[key] = ttl
        return True

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                self._ttl.pop(k, None)
                n += 1
        return n

    def expire(self, key, ttl):
        """设置 key 的 TTL（秒）。key 不存在返回 False。"""
        if key in self._store:
            self._ttl[key] = ttl
            return True
        return False

    def ttl(self, key):
        """返回剩余 TTL（秒）。key 不存在返回 -2，存在但无 TTL 返回 -1。"""
        if key not in self._store:
            return -2
        return self._ttl.get(key, -1)

    def exists(self, key):
        return int(key in self._store)

    def lpush(self, key, value):
        return 1

    def brpop(self, key, timeout=0):
        return None

    def publish(self, channel, message):
        return 0


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """全局替换 get_redis，避免测试连真实 Redis。"""
    import app.core.redis_client as rc

    rc._redis = FakeRedis()
    yield
    rc._redis = None

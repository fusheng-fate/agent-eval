"""flow_templates 模块测试夹具：内存 SQLite + 假 Redis（自包含，不依赖 tests/conftest.py）。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

# 复用 tests/conftest.py 的 SQLite JSONB/ARRAY 适配（导入即生效）
import tests.conftest  # noqa: F401  触发 @compiles 注册

from app.core.database import Base  # noqa: E402


class _FakeRedis:
    def __init__(self):
        self._store = {}

    def incr(self, key):
        return 1

    def decr(self, key):
        return 0

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, ex=None):
        self._store[key] = value
        return True

    def exists(self, key):
        return int(key in self._store)


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
    import app.core.redis_client as rc

    rc._redis = _FakeRedis()
    yield
    rc._redis = None

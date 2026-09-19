"""应用工厂 + 生命周期（建表/引导/起 worker）。

启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core.bootstrap import bootstrap_admin, bootstrap_standard_evaluator, init_db
from .core.config import settings
from .core.database import SessionLocal
from .core.redis_client import health as redis_health
from .modules.auth import routes as auth_routes
from .modules.configs import routes as configs_routes
from .modules.datasets import routes as datasets_routes
from .modules.evaluators import routes as evaluators_routes
from .modules.flow_templates import routes as flow_templates_routes
from .modules.metrics import routes as metrics_routes
from .modules.reports import routes as reports_routes
from .modules.runs import routes as runs_routes
from .modules.runs import worker
from .modules.users import routes as users_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    init_db()
    db = SessionLocal()
    try:
        bootstrap_admin(db)
        bootstrap_standard_evaluator(db)
        _seed_configs(db)
    finally:
        db.close()
    worker.start_workers()
    log.info("%s started (redis=%s)", settings.APP_NAME, "ok" if redis_health() else "DOWN")
    yield
    # 关闭
    worker.stop_workers()


def _seed_configs(db) -> None:
    """首次启动写入默认配置项（幂等）。"""
    from .models import Config
    defaults = {
        "llm.base_url": {"value": settings.LLM_BASE_URL, "editable_by": "admin", "scope": "global", "description": "接口地址"},
        "llm.api_key": {"value": settings.LLM_API_KEY, "editable_by": "admin", "scope": "global", "description": "API 密钥"},
        "llm.auth": {"value": {"type": "static", "token_in": "header", "token_name": "Authorization", "token_prefix": "Bearer "}, "editable_by": "admin", "scope": "global", "description": "认证方式"},
        "llm.model": {"value": settings.LLM_MODEL, "editable_by": "admin", "scope": "global", "description": "模型名称"},
        "llm.max_tokens": {"value": settings.LLM_MAX_TOKENS, "editable_by": "admin", "scope": "global", "description": "最大 Token"},
        "llm.timeout": {"value": settings.LLM_TIMEOUT, "editable_by": "admin", "scope": "global", "description": "超时（秒）"},
        "llm.retry_count": {"value": settings.LLM_RETRY_COUNT, "editable_by": "admin", "scope": "global", "description": "调用重试次数"},
        "llm.retry_backoff": {"value": settings.LLM_RETRY_BACKOFF, "editable_by": "admin", "scope": "global", "description": "重试间隔（秒）"},
        "target.endpoint": {"value": settings.TARGET_ENDPOINT, "editable_by": "admin", "scope": "global", "description": "被测 Agent 地址"},
        "concurrency.model": {"value": settings.CONCURRENCY_MODEL, "editable_by": "admin", "scope": "global", "description": "模型并发上限"},
        "report.pass_threshold": {"value": settings.PASS_THRESHOLD, "editable_by": "admin", "scope": "global", "description": "通过阈值"},
        "evaluator.extra_metric_limit": {"value": 5, "editable_by": "admin", "scope": "global", "description": "额外指标数量上限"},
    }
    for key, meta in defaults.items():
        exists = db.query(Config).filter(Config.config_key == key).first()
        if exists:
            # 同步展示名称（description 为展示文案，非用户数据），存量库也能用上新标签
            if exists.description != meta["description"]:
                exists.description = meta["description"]
            # llm.retry_backoff 的默认值从 1 升到 3：只把"仍是旧默认 1"的存量库刷成 3，
            # 用户手动改过的值（非 1）不动，避免覆盖自定义配置。
            if key == "llm.retry_backoff":
                cur_val = exists.config_value.get("value") if isinstance(exists.config_value, dict) else exists.config_value
                if cur_val == 1:
                    exists.config_value = {"value": meta["value"]}
            continue
        db.add(Config(
            config_key=key, config_value={"value": meta["value"]},
            scope=meta["scope"], editable_by=meta["editable_by"], description=meta["description"],
        ))
    # 分制迁移：存量库的通过阈值若仍是 0-5 量级（≤5），升到百分制默认 80。
    # 管理员在配置中心手动改过的更高值（>5）不动。
    pt = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    if pt is not None:
        cur = pt.config_value.get("value")
        try:
            if float(cur) <= 5:
                pt.config_value = {**pt.config_value, "value": settings.PASS_THRESHOLD}
        except (TypeError, ValueError):
            pass
    db.commit()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.API_PREFIX
    app.include_router(auth_routes.router, prefix=prefix)
    app.include_router(users_routes.router, prefix=prefix)
    app.include_router(metrics_routes.router, prefix=prefix)
    app.include_router(evaluators_routes.router, prefix=prefix)
    app.include_router(datasets_routes.router, prefix=prefix)
    app.include_router(flow_templates_routes.router, prefix=prefix)
    app.include_router(runs_routes.router, prefix=prefix)
    app.include_router(runs_routes.dashboard_router, prefix=prefix)
    app.include_router(reports_routes.router, prefix=prefix)
    app.include_router(configs_routes.router, prefix=prefix)

    # 纯 ASGI 中间件：拦截 4xx/5xx 的 {"detail":...} 响应，包裹为 {code, message, data}
    code_map = {400: 40001, 401: 40101, 403: 40301, 404: 40401, 409: 40901, 422: 42201}

    class WrapErrorMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            status_holder = {"status": 200}
            buffered = {"start": None, "body": b"", "done": False}

            async def send_wrapper(message):
                mtype = message["type"]
                if mtype == "http.response.start":
                    status_holder["status"] = message.get("status", 200)
                    buffered["start"] = message
                    return  # 暂存，等 body 到齐再决定
                if mtype == "http.response.body":
                    buffered["body"] += message.get("body", b"")
                    if message.get("more_body", False):
                        return  # 还有后续 body
                    buffered["done"] = True
                    # body 到齐，判断是否包裹
                    st = status_holder["status"]
                    headers = buffered["start"].get("headers", [])
                    ct = b""
                    for k, v in headers:
                        if k.lower() == b"content-type":
                            ct = v.lower()
                    if st >= 400 and b"application/json" in ct:
                        import json as _json
                        try:
                            data = _json.loads(buffered["body"])
                            if "detail" in data and "code" not in data:
                                code = code_map.get(st, st * 100 + 1)
                                new_body = _json.dumps(
                                    {"code": code, "message": str(data["detail"]), "data": None},
                                    ensure_ascii=False,
                                ).encode("utf-8")
                                await send({
                                    "type": "http.response.start",
                                    "status": st,
                                    "headers": [
                                        (b"content-type", b"application/json; charset=utf-8"),
                                        (b"content-length", str(len(new_body)).encode()),
                                    ],
                                })
                                await send({"type": "http.response.body", "body": new_body})
                                return
                        except Exception:
                            pass
                    # 不包裹：原样发送
                    out_headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                    out_headers.append((b"content-length", str(len(buffered["body"])).encode()))
                    await send({
                        "type": "http.response.start",
                        "status": st,
                        "headers": out_headers,
                    })
                    await send({"type": "http.response.body", "body": buffered["body"]})
                    return

            await self.app(scope, receive, send_wrapper)

    app.add_middleware(WrapErrorMiddleware)

    @app.get(f"{prefix}/health")
    def health():
        from .core.database import engine
        db_ok = True
        try:
            with engine.connect():
                pass
        except Exception:
            db_ok = False
        return {"status": "ok", "db": db_ok, "redis": redis_health()}

    _mount_frontend(app, prefix)

    return app


def _mount_frontend(app: FastAPI, prefix: str) -> None:
    """方案 B：后端顺带托管前端静态产物（SPA）。

    前端构建产物（`dev/web/dist`）由 Dockerfile 多阶段构建 COPY 进镜像，
    默认落在 `web/` 目录（可用环境变量 FRONTEND_DIR 覆盖）。此处：
      1. 挂载 `/assets` 等静态资源；
      2. 兜底路由把非 `/api` 的路径回退到 `index.html`（SPA 前端路由）。

    本地未构建前端（目录不存在）时静默跳过，不影响纯后端开发/测试。
    """
    frontend_dir = Path(settings.FRONTEND_DIR)
    index_html = frontend_dir / "index.html"
    if not index_html.is_file():
        log.info("frontend dist not found at %s, serving API only", frontend_dir)
        return

    app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith(prefix.lstrip("/")):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index_html)





app = create_app()

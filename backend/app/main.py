import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.academic import router as academic_router
from .api.auth import router as auth_router
from .api.chat import router as chat_router
from .api.confirm import router as confirm_router
from .api.replay import router as replay_router
from .auth.rate_limit import LoginGuard
from .auth.session import SessionStore
from .auth.students import build_student_repository, seed_students
from .config import get_settings
from .db.base import Database
from .db.database import build_database
from .db.migrations import assert_current_schema, run_migrations
from .db.repository import build_repository
from .llm import build_provider
from .tools.base import ToolRegistry
from .tools.composite import CompositeRegistry
from .tools.stdio_mcp import stdio_registry
from .write_ops import PendingActionStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("campus-agent")


def _academic_env(settings) -> dict[str, str]:
    """显式传库配置给 academic 子进程——env=None 时 MCP 只透传白名单变量。"""
    return {
        **os.environ,
        "DB_BACKEND": settings.db_backend,
        "SQLITE_PATH": str(settings.sqlite_path),
        "MYSQL_HOST": settings.mysql_host,
        "MYSQL_PORT": str(settings.mysql_port),
        "MYSQL_USER": settings.mysql_user,
        "MYSQL_PASSWORD": settings.mysql_password,
        "MYSQL_DATABASE": settings.mysql_database,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.provider = build_provider(settings)
    db: Database = build_database(settings)
    await run_migrations(db)
    await assert_current_schema(db)
    app.state.db = db
    await seed_students(db)
    app.state.repository = build_repository(db)
    app.state.students = build_student_repository(db)
    app.state.sessions = SessionStore(ttl_seconds=settings.session_ttl_seconds)
    app.state.pending_actions = PendingActionStore()  # 待确认写动作，/confirm 从这里 pop
    app.state.login_guard = LoginGuard()
    async with stdio_registry(settings.navigation_server_dir) as nav_reg, \
               stdio_registry(settings.academic_server_dir, env=_academic_env(settings)) as academic_reg:
        registry = CompositeRegistry([nav_reg, academic_reg])
        app.state.registry = registry
        logger.info("MCP tools ready: %s", [t.name for t in await registry.list_tools()])
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="campus-agent", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],  # 显式白名单，不用 "*"
        allow_credentials=True,                # HttpOnly 会话 Cookie 需要
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/debug/tools")
    async def debug_tools():
        registry: ToolRegistry = app.state.registry
        return {"tools": [t.model_dump() for t in await registry.list_tools()]}

    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(academic_router)
    app.include_router(confirm_router)
    app.include_router(replay_router)

    return app


app = create_app()

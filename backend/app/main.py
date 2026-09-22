import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.academic import router as academic_router
from .api.auth import router as auth_router
from .api.chat import router as chat_router
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
from .tools.stdio_mcp import stdio_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("campus-agent")


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
    app.state.login_guard = LoginGuard()
    async with stdio_registry(settings.navigation_server_dir) as registry:
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

    return app


app = create_app()

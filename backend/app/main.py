import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.auth import router as auth_router
from .api.chat import router as chat_router
from .auth.rate_limit import LoginGuard
from .auth.session import SessionStore
from .auth.students import build_student_repository, seed_students
from .config import get_settings
from .db.engine import init_db
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
    await init_db(settings.sqlite_path)
    await seed_students(settings.sqlite_path)
    app.state.repository = build_repository(settings.sqlite_path)
    app.state.students = build_student_repository(settings.sqlite_path)
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

    return app


app = create_app()

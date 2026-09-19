from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M3 在此拉起 StdioMcpRegistry；M6 在此 init_db
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="campus-agent", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()

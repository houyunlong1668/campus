from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_origin: str = "http://localhost:5173"
    navigation_server_dir: Path = Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "navigation"
    llm_provider: str = "fake"
    openai_base_url: str = ""
    openai_model: str = ""
    openai_api_key: str = ""
    sqlite_path: Path = Path(__file__).resolve().parent.parent / "data" / "campus.db"
    # 仿真用户：只从会话侧取，永不来自请求体（spec 6.1）
    fake_student_id: str = "20230001"
    cookie_secure: bool = False
    session_ttl_seconds: int = 43200


@lru_cache
def get_settings() -> Settings:
    return Settings()

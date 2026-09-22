from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_origin: str = "http://localhost:5173"
    navigation_server_dir: Path = Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "navigation"
    academic_server_dir: Path = Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "academic"
    llm_provider: str = "fake"
    openai_base_url: str = ""
    openai_model: str = ""
    openai_api_key: str = ""
    sqlite_path: Path = Path(__file__).resolve().parent.parent / "data" / "campus.db"
    db_backend: str = "mysql"  # mysql | sqlite；sqlite 用于无 Docker 机器与全部测试
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "campus"
    # 仿真用户：只从会话侧取，永不来自请求体（spec 6.1）
    fake_student_id: str = "20230001"
    cookie_secure: bool = False
    session_ttl_seconds: int = 43200
    history_limit: int = 6   # spec 12：6 轮上限，每条另截 200 字


@lru_cache
def get_settings() -> Settings:
    return Settings()

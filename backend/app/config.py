from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_origin: str = "http://localhost:5173"
    navigation_server_dir: Path = Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "navigation"
    # M6 会在此追加：llm_provider / openai_base_url / openai_model / openai_api_key
    # 及 sqlite_path / fake_student_id


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Dockseal API"

    database_url: str = "sqlite:///./dockseal.db"

    jwt_secret: str = "troque-esta-chave-em-producao-dockseal-tcc"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4.1-mini"
    openai_ocr_model: str = "gpt-4.1"

    # Origens do front-end autorizadas a chamar a API pelo navegador (CORS).
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    upload_dir: Path = Path("uploads")
    max_upload_size_mb: int = 20
    max_files_per_analysis: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()

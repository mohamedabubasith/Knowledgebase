from functools import lru_cache
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Local Knowledge Base"
    environment: str = "production"
    database_url: str
    secret_key: str
    super_admin_email: str = "admin@example.com"
    super_admin_password: str = "Admin@123"
    redis_url: str = "redis://redis:6379/0"
    ollama_url: str = "http://ollama:11434"
    embed_model: str = "nomic-embed-text"
    llm_model: str = "llama3.2:3b"
    upload_dir: Path = Path("/app/uploads")
    max_upload_size_mb: int = 100
    chunk_size: int = 512
    chunk_overlap: int = 64
    cors_origins: list[str] = ["*"]
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @field_validator("database_url")
    @classmethod
    def async_database_url(cls, value: str) -> str:
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)

    @field_validator("secret_key")
    @classmethod
    def secure_secret(cls, value: str) -> str:
        if len(value) < 32: raise ValueError("SECRET_KEY must contain at least 32 characters")
        return value

@lru_cache
def get_settings() -> Settings: return Settings()
settings = get_settings()

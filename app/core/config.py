from functools import lru_cache
from pathlib import Path
from pydantic import AliasChoices,Field,field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Local Knowledge Base"
    environment: str = "production"
    database_url: str = Field(validation_alias=AliasChoices("DATABASE_URL","POSTGRES_DSN"))
    secret_key: str = Field(validation_alias=AliasChoices("SECRET_KEY","APP_SECRET_KEY"))
    super_admin_email: str = "admin@example.com"
    super_admin_password: str = "Admin@123"
    redis_url: str = "redis://redis:6379/0"
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_dimension: int = 384
    hf_home: Path = Path("/app/models")
    hf_token: str = ""
    qdrant_url: str
    qdrant_api_key: str = ""
    qdrant_prefer_grpc: bool = False
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = Field(default="kb-documents",validation_alias=AliasChoices("MINIO_BUCKET","MINIO_BUCKET_RAW"))
    minio_use_ssl: bool = Field(default=False,validation_alias=AliasChoices("MINIO_USE_SSL","MINIO_SECURE"))
    postgres_pool_min: int = 5
    postgres_pool_max: int = 20
    qdrant_collection: str = "cortex_kb"
    chroma_persist_dir: str = "/app/chroma"
    unstructured_api_url: str = ""
    unstructured_api_key: str = ""
    unstructured_local_url: str = ""
    st_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_batch_size: int = 32
    embedding_max_tokens: int = 512
    hybrid_vector_weight: float = 0.7
    hybrid_lexical_weight: float = 0.3
    search_cache_ttl: int = 300
    search_cache_max: int = 1000
    tabular_sql_base_url: str = ""
    tabular_sql_api_key: str = ""
    tabular_sql_model: str = ""
    tabular_max_result_rows: int = 100
    mindsdb_url: str = ""
    upload_dir: Path = Path("/app/uploads")
    max_upload_size_mb: int = 100
    chunk_size: int = 512
    chunk_overlap: int = 64
    cors_origins: list[str] = ["*"]
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    n8n_password_reset_webhook: str = ""
    n8n_invite_webhook: str = ""
    app_base_url: str = "http://localhost:3000"
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

    @property
    def postgres_dsn(self) -> str:
        return self.database_url

    @property
    def app_secret_key(self) -> str:
        return self.secret_key

    @property
    def minio_bucket_raw(self) -> str:
        return self.minio_bucket

    @property
    def minio_secure(self) -> bool:
        return self.minio_use_ssl

@lru_cache
def get_settings() -> Settings: return Settings()
settings = get_settings()

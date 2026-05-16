from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "production"
    app_secret_key: str = "change-me-insecure-default"
    log_level: str = "INFO"

    # Postgres
    postgres_dsn: str = "postgresql://cortex:cortex@localhost:5432/cortex_kb"
    postgres_pool_min: int = 5
    postgres_pool_max: int = 20

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_raw: str = "raw-documents"
    minio_secure: bool = False

    # Qdrant
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "cortex_kb"

    # ChromaDB fallback
    chroma_persist_dir: str = "./data/chroma"

    # Unstructured
    unstructured_api_url: str = ""
    unstructured_api_key: str = ""
    unstructured_local_url: str = "http://localhost:8000"

    # Embeddings
    ollama_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    st_model: str = "paraphrase-multilingual-mpnet-base-v2"  # 768-dim — matches Ollama paraphrase-multilingual
    # Max tokens the embedding model accepts (model's native tokenizer tokens).
    # paraphrase-multilingual:latest (GGUF bert) = 512 context_length → use 500 (leaves room for [CLS]/[SEP])
    # nomic-embed-text                           = 8192
    # mxbai-embed-large                          = 512
    # Set in .env as EMBEDDING_MAX_TOKENS to match whichever model you use.
    embedding_max_tokens: int = 500  # default: paraphrase-multilingual (512 context − 12 special tokens)

    # Workers
    worker_concurrency: int = 4
    parse_process_workers: int = 2
    embed_batch_size: int = 64
    ingest_queue_size: int = 500

    # Search
    search_top_k: int = 10
    hybrid_vector_weight: float = 0.6
    hybrid_lexical_weight: float = 0.4
    search_cache_ttl: int = 300
    search_cache_max: int = 1000

    # Tabular NL2SQL
    # Model used to generate SQL from natural language. Must be available in Ollama.
    # Recommended: qwen2.5:7b (fast + good SQL), or any instruct model.
    tabular_sql_model: str = "qwen2.5:7b"
    # Max rows DuckDB will return for a single tabular query
    tabular_max_result_rows: int = 100

    # JWT
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60


settings = Settings()

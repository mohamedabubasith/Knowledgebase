"""
Shared fixtures.
DB, MinIO, vector store, embedder are always mocked.
Registry is reset to unfrozen before each test.
"""
import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.registry import ServiceRegistry


# ── Registry reset ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure registry is fresh and unfrozen for every test."""
    import app.core.registry as reg_module
    reg_module.registry = ServiceRegistry()
    yield
    reg_module.registry = ServiceRegistry()


@pytest.fixture
def frozen_qdrant_registry():
    import app.core.registry as reg_module
    reg_module.registry.parse_backend = "local_parsers"
    reg_module.registry.embed_backend = "sentence_transformers"
    reg_module.registry.embed_dimension = 384
    reg_module.registry.embed_model_name = "all-MiniLM-L6-v2"
    reg_module.registry.vector_backend = "qdrant"
    reg_module.registry.search_mode = "hybrid"
    reg_module.registry.freeze()
    return reg_module.registry


@pytest.fixture
def frozen_chroma_registry():
    import app.core.registry as reg_module
    reg_module.registry.parse_backend = "local_parsers"
    reg_module.registry.embed_backend = "sentence_transformers"
    reg_module.registry.embed_dimension = 384
    reg_module.registry.embed_model_name = "all-MiniLM-L6-v2"
    reg_module.registry.vector_backend = "chroma"
    reg_module.registry.search_mode = "hybrid"
    reg_module.registry.freeze()
    return reg_module.registry


# ── Mock DB pool ──────────────────────────────────────────────────────────────

@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    conn.executemany = AsyncMock(return_value=None)
    return conn


@pytest.fixture
def mock_pool(mock_conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.fixture(autouse=True)
def patch_pool(mock_pool):
    with patch("app.db.pool._pool", mock_pool):
        yield mock_pool


# ── Sample data ───────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
DOCUMENT_ID = "22222222-2222-2222-2222-222222222222"
CHUNK_ID = "33333333-3333-3333-3333-333333333333"
API_KEY_RAW = "cortex_testkey123"
API_KEY_HASH = hashlib.sha256(API_KEY_RAW.encode()).hexdigest()


@pytest.fixture
def sample_api_key_row():
    return {
        "id": "44444444-4444-4444-4444-444444444444",
        "tenant_id": TENANT_ID,
        "role": "editor",
    }


@pytest.fixture
def sample_chunk_rows():
    return [
        {
            "id": CHUNK_ID,
            "document_id": DOCUMENT_ID,
            "chunk_index": 0,
            "chunk_text": "The quick brown fox jumps over the lazy dog.",
            "token_count": 10,
            "page_number": 1,
            "start_char": 0,
            "end_char": 44,
            "checksum": hashlib.sha256(b"The quick brown fox jumps over the lazy dog.").hexdigest(),
        }
    ]


@pytest.fixture
def sample_document_row():
    from datetime import datetime, timezone
    return {
        "id": DOCUMENT_ID,
        "tenant_id": TENANT_ID,
        "filename": "test.pdf",
        "mime_type": "application/pdf",
        "minio_path": f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf",
        "file_size": 1024,
        "parse_mode": "pymupdf",
        "status": "indexed",
        "page_count": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "checksum": "abc123",
    }

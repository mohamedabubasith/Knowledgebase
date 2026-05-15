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
def patch_pool(mock_pool, mock_sa_factory):
    """
    Two-layer DB mock:
    1. Legacy asyncpg pool shim (create=True so it doesn't crash if absent).
    2. SA session factory — patches AsyncSessionLocal so get_session_factory()
       returns mock_sa_factory globally, covering deps + workers.
    """
    import app.db.session as _sess
    original_asl = _sess.AsyncSessionLocal
    _sess.AsyncSessionLocal = mock_sa_factory
    with patch("app.db.pool._pool", mock_pool, create=True):
        yield mock_pool
    _sess.AsyncSessionLocal = original_asl


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


# ── SQLAlchemy async session mocks ────────────────────────────────────────────

@pytest.fixture
def mock_sa_result():
    """Generic SQLAlchemy execute result — call .scalar_one_or_none() or .scalars().all()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.rowcount = 0
    return result


@pytest.fixture
def mock_sa_session(mock_sa_result):
    """Mock SQLAlchemy AsyncSession."""
    import uuid as _uuid_mod

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_sa_result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.expunge = MagicMock()

    # refresh() simulates DB populating server-defaults (e.g. UUID primary key)
    async def _refresh(obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = str(_uuid_mod.uuid4())
    session.refresh = AsyncMock(side_effect=_refresh)

    # session.begin() — async context manager used by claim() for SELECT FOR UPDATE
    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)
    return session


@pytest.fixture
def mock_sa_factory(mock_sa_session):
    """
    Mock for get_session_factory().
    Calling mock_sa_factory() returns an async context manager that yields mock_sa_session.
    """
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_sa_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=cm)
    return factory


JOB_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

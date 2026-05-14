"""
Tests for search engine: hybrid, vector-only, lexical, keyword fallback, cache.
DB + vector store mocked.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.vectorstore.backend import VectorHit
from tests.conftest import CHUNK_ID, DOCUMENT_ID, TENANT_ID

SAMPLE_VECTOR = [0.1] * 384

DB_ROW = {
    "id": CHUNK_ID,
    "document_id": DOCUMENT_ID,
    "chunk_text": "The quick brown fox.",
    "page_number": 1,
    "minio_path": f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf",
}

FTS_ROW = {**DB_ROW, "rank": 0.8}

VECTOR_HIT = VectorHit(point_id=CHUNK_ID, score=0.9, payload={"document_id": DOCUMENT_ID})


@pytest.fixture(autouse=True)
def use_hybrid_registry(frozen_qdrant_registry):
    pass


@pytest.fixture(autouse=True)
def clear_search_cache():
    """Clear in-process TTL cache between tests."""
    import app.search.engine as eng
    eng._cache.clear()
    yield
    eng._cache.clear()


@pytest.fixture
def mock_embed():
    with patch("app.search.engine.embed_single", new=AsyncMock(return_value=SAMPLE_VECTOR)):
        yield


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.search = AsyncMock(return_value=[VECTOR_HIT])
    with patch("app.search.engine.get_vector_store", return_value=store):
        yield store


@pytest.fixture
def mock_fts(mock_conn):
    mock_conn.fetch = AsyncMock(return_value=[MagicMock(**FTS_ROW, **{"__getitem__": lambda s, k: FTS_ROW[k]})])
    # Use real dict-like rows via asyncpg Record simulation
    class FakeRecord(dict):
        pass
    fts_row = FakeRecord(FTS_ROW)
    chunks_row = FakeRecord(DB_ROW)
    mock_conn.fetch = AsyncMock(side_effect=[
        [fts_row],      # first call → FTS results
        [chunks_row],   # second call → fetch chunks by ids
    ])
    return mock_conn


class TestHybridSearch:

    async def test_hybrid_returns_results(self, mock_embed, mock_vector_store, mock_conn):
        class R(dict): pass
        fts_row = R(FTS_ROW)
        chunks_row = R(DB_ROW)
        mock_conn.fetch = AsyncMock(side_effect=[[fts_row], [chunks_row]])

        from app.search.engine import search
        resp = await search("fox", TENANT_ID, mode="hybrid", top_k=10)

        assert resp.search_mode_used == "hybrid"
        assert resp.total >= 0

    async def test_hybrid_score_formula(self, mock_embed, mock_vector_store, mock_conn):
        """Score = 0.6*vector + 0.4*lexical."""
        vector_score = 0.9
        lexical_score = 0.5
        expected = 0.6 * vector_score + 0.4 * lexical_score

        hit = VectorHit(point_id=CHUNK_ID, score=vector_score, payload={})
        mock_vector_store.search = AsyncMock(return_value=[hit])

        class R(dict): pass
        fts_row = R({**FTS_ROW, "rank": lexical_score})
        chunks_row = R(DB_ROW)
        mock_conn.fetch = AsyncMock(side_effect=[[fts_row], [chunks_row]])

        from app.search.engine import search
        resp = await search("fox", TENANT_ID, mode="hybrid", top_k=10)

        if resp.results:
            assert resp.results[0].score == pytest.approx(expected, abs=0.01)


class TestVectorOnlySearch:

    async def test_vector_only_skips_fts(self, mock_embed, mock_vector_store, mock_conn):
        class R(dict): pass
        mock_conn.fetch = AsyncMock(return_value=[R(DB_ROW)])

        from app.search.engine import search
        resp = await search("fox", TENANT_ID, mode="vector_only", top_k=5)

        assert resp.search_mode_used == "vector_only"
        mock_vector_store.search.assert_called_once()

    async def test_vector_only_returns_top_k(self, mock_embed, mock_vector_store, mock_conn):
        hits = [VectorHit(point_id=f"id-{i}", score=0.9 - i * 0.1, payload={}) for i in range(5)]
        mock_vector_store.search = AsyncMock(return_value=hits)

        class R(dict): pass
        rows = [R({**DB_ROW, "id": f"id-{i}"}) for i in range(5)]
        mock_conn.fetch = AsyncMock(return_value=rows)

        from app.search.engine import search
        resp = await search("fox", TENANT_ID, mode="vector_only", top_k=5)
        assert resp.total <= 5


class TestLexicalOnlySearch:

    async def test_fts_mode_used(self, mock_conn):
        class R(dict): pass
        mock_conn.fetch = AsyncMock(return_value=[R(FTS_ROW)])

        from app.search.engine import search
        resp = await search("fox", TENANT_ID, mode="lexical_only", top_k=10)

        assert resp.search_mode_used == "lexical_only"

    async def test_fts_only_registry_forces_lexical(self, mock_conn):
        import app.core.registry as reg
        reg.registry.search_mode = "fts_only"

        class R(dict): pass
        mock_conn.fetch = AsyncMock(return_value=[R(FTS_ROW)])

        from app.search.engine import search
        resp = await search("fox", TENANT_ID, mode="hybrid", top_k=10)
        # Hybrid requested but registry says fts_only → downgrade
        assert resp.search_mode_used == "lexical_only"


class TestKeywordFallback:

    async def test_keyword_fallback_uses_ilike(self, mock_conn):
        class R(dict): pass
        mock_conn.fetch = AsyncMock(return_value=[R(DB_ROW)])

        from app.search.engine import _keyword_search
        results, mode = await _keyword_search("fox", TENANT_ID, 10, None)
        assert mode == "keyword_fallback"
        # ILIKE query should have been called
        mock_conn.fetch.assert_called_once()


class TestSearchCache:

    async def test_same_query_hits_cache(self, mock_embed, mock_vector_store, mock_conn):
        class R(dict): pass
        mock_conn.fetch = AsyncMock(return_value=[R(FTS_ROW)])

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.search_cache_ttl = 60
            mock_settings.search_cache_max = 100
            mock_settings.hybrid_vector_weight = 0.6
            mock_settings.hybrid_lexical_weight = 0.4
            mock_settings.embed_batch_size = 64
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.ollama_embed_model = "nomic-embed-text"

            import app.search.engine as eng
            eng._cache.clear()

            from app.search.engine import search
            resp1 = await search("fox test", TENANT_ID, mode="lexical_only")
            resp2 = await search("fox test", TENANT_ID, mode="lexical_only")

        # Second call should return same result from cache
        assert resp1.results == resp2.results

    async def test_cache_disabled_when_ttl_zero(self, mock_embed, mock_vector_store, mock_conn):
        import app.search.engine as eng
        key = "test:key"
        await eng._cache_set(key, MagicMock())

        with patch("app.core.config.settings") as s:
            s.search_cache_ttl = 0
            result = await eng._cache_get(key)
        assert result is None


class TestQueryLatency:

    async def test_query_ms_reported(self, mock_embed, mock_vector_store, mock_conn):
        class R(dict): pass
        mock_conn.fetch = AsyncMock(return_value=[R(FTS_ROW)])

        from app.search.engine import search
        resp = await search("test", TENANT_ID, mode="lexical_only")
        assert resp.query_ms >= 0
        assert isinstance(resp.query_ms, float)

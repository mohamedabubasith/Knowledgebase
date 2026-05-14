"""
Tests for QdrantStore and ChromaStore — all external clients mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.vectorstore.backend import VectorHit, VectorPoint

TENANT_ID = "11111111-1111-1111-1111-111111111111"
DOC_ID = "22222222-2222-2222-2222-222222222222"
CHUNK_ID = "33333333-3333-3333-3333-333333333333"

SAMPLE_POINT = VectorPoint(
    point_id=CHUNK_ID,
    vector=[0.1] * 384,
    payload={"tenant_id": TENANT_ID, "document_id": DOC_ID, "chunk_index": 0},
)


# ── QdrantStore ───────────────────────────────────────────────────────────────

class TestQdrantStore:

    @pytest.fixture
    def mock_qdrant_client(self):
        client = AsyncMock()
        client.upsert = AsyncMock()
        client.search = AsyncMock(return_value=[])
        client.delete = AsyncMock()
        client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
        return client

    @pytest.fixture
    def qdrant_store(self, mock_qdrant_client):
        with patch("app.vectorstore.qdrant_store.AsyncQdrantClient", return_value=mock_qdrant_client):
            from app.vectorstore.qdrant_store import QdrantStore
            store = QdrantStore()
            store._client = mock_qdrant_client
            return store

    async def test_upsert_batch_calls_client(self, qdrant_store, mock_qdrant_client):
        await qdrant_store.upsert_batch([SAMPLE_POINT])
        mock_qdrant_client.upsert.assert_called_once()

    async def test_upsert_batch_empty_no_call(self, qdrant_store, mock_qdrant_client):
        await qdrant_store.upsert_batch([])
        mock_qdrant_client.upsert.assert_not_called()

    async def test_upsert_large_batch_splits(self, qdrant_store, mock_qdrant_client):
        points = [
            VectorPoint(point_id=f"id-{i}", vector=[0.1] * 384, payload={})
            for i in range(300)  # > _BATCH_SIZE=256
        ]
        await qdrant_store.upsert_batch(points)
        # Should call upsert twice: 256 + 44
        assert mock_qdrant_client.upsert.call_count == 2

    async def test_search_applies_tenant_filter(self, qdrant_store, mock_qdrant_client):
        mock_result = MagicMock()
        mock_result.id = CHUNK_ID
        mock_result.score = 0.9
        mock_result.payload = {"tenant_id": TENANT_ID}
        mock_qdrant_client.search = AsyncMock(return_value=[mock_result])

        hits = await qdrant_store.search([0.1] * 384, TENANT_ID, top_k=5)
        assert len(hits) == 1
        assert hits[0].point_id == CHUNK_ID
        assert hits[0].score == pytest.approx(0.9)

        # Verify filter contains tenant_id
        call_kwargs = mock_qdrant_client.search.call_args[1]
        filter_obj = call_kwargs["query_filter"]
        conditions = filter_obj.must
        keys = [c.key for c in conditions]
        assert "tenant_id" in keys

    async def test_search_with_document_id_filter(self, qdrant_store, mock_qdrant_client):
        mock_qdrant_client.search = AsyncMock(return_value=[])
        await qdrant_store.search([0.1] * 384, TENANT_ID, top_k=5, document_id=DOC_ID)
        call_kwargs = mock_qdrant_client.search.call_args[1]
        conditions = call_kwargs["query_filter"].must
        keys = [c.key for c in conditions]
        assert "document_id" in keys

    async def test_delete_by_document(self, qdrant_store, mock_qdrant_client):
        await qdrant_store.delete_by_document(DOC_ID, TENANT_ID)
        mock_qdrant_client.delete.assert_called_once()

    async def test_health_check_ok(self, qdrant_store, mock_qdrant_client):
        result = await qdrant_store.health_check()
        assert result is True

    async def test_health_check_fail(self, qdrant_store, mock_qdrant_client):
        mock_qdrant_client.get_collections.side_effect = Exception("connection refused")
        result = await qdrant_store.health_check()
        assert result is False


# ── ChromaStore ───────────────────────────────────────────────────────────────

class TestChromaStore:

    @pytest.fixture
    def mock_collection(self):
        col = MagicMock()
        col.count.return_value = 0
        col.upsert.return_value = None
        col.query.return_value = {
            "ids": [[CHUNK_ID]],
            "distances": [[0.1]],
            "metadatas": [[{"tenant_id": TENANT_ID, "document_id": DOC_ID}]],
        }
        col.delete.return_value = None
        return col

    @pytest.fixture
    def chroma_store(self, mock_collection):
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        with patch("app.vectorstore.chroma_store.chromadb.PersistentClient", return_value=mock_client), \
             patch("os.makedirs"):
            from app.vectorstore.chroma_store import ChromaStore
            store = ChromaStore()
            store._collection = mock_collection
            return store

    async def test_upsert_batch(self, chroma_store, mock_collection):
        await chroma_store.upsert_batch([SAMPLE_POINT])
        mock_collection.upsert.assert_called_once()
        call_kwargs = mock_collection.upsert.call_args[1]
        assert CHUNK_ID in call_kwargs["ids"]

    async def test_search_returns_hits(self, chroma_store, mock_collection):
        hits = await chroma_store.search([0.1] * 384, TENANT_ID, top_k=5)
        assert len(hits) == 1
        assert hits[0].point_id == CHUNK_ID
        # cosine: score = 1 - distance = 1 - 0.1 = 0.9
        assert hits[0].score == pytest.approx(0.9)

    async def test_search_tenant_filter_no_doc_id(self, chroma_store, mock_collection):
        mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]]}
        await chroma_store.search([0.1] * 384, TENANT_ID, top_k=5)
        call_kwargs = mock_collection.query.call_args[1]
        where = call_kwargs["where"]
        # Should be plain field filter
        assert where == {"tenant_id": {"$eq": TENANT_ID}}

    async def test_search_tenant_and_doc_filter(self, chroma_store, mock_collection):
        mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]]}
        await chroma_store.search([0.1] * 384, TENANT_ID, top_k=5, document_id=DOC_ID)
        call_kwargs = mock_collection.query.call_args[1]
        where = call_kwargs["where"]
        assert "$and" in where

    async def test_delete_by_document(self, chroma_store, mock_collection):
        await chroma_store.delete_by_document(DOC_ID, TENANT_ID)
        mock_collection.delete.assert_called_once()
        call_kwargs = mock_collection.delete.call_args[1]
        assert "$and" in call_kwargs["where"]

    async def test_health_check_ok(self, chroma_store, mock_collection):
        result = await chroma_store.health_check()
        assert result is True

    async def test_health_check_fail(self, chroma_store, mock_collection):
        mock_collection.count.side_effect = Exception("db error")
        result = await chroma_store.health_check()
        assert result is False

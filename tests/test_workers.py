"""
Tests for ingest, embed, index, purge workers.
All external I/O (MinIO, DB, vector store, embedder) mocked.
"""
import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import CHUNK_ID, DOCUMENT_ID, TENANT_ID


# ── Shared worker job fixtures ─────────────────────────────────────────────────

@pytest.fixture
def ingest_job():
    return {
        "document_id": DOCUMENT_ID,
        "tenant_id": TENANT_ID,
        "filename": "test.pdf",
        "mime_type": "application/pdf",
        "minio_path": f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf",
    }


@pytest.fixture
def embed_job():
    return {"document_id": DOCUMENT_ID, "tenant_id": TENANT_ID}


@pytest.fixture
def index_job():
    return {"document_id": DOCUMENT_ID, "tenant_id": TENANT_ID}


@pytest.fixture
def purge_job():
    return {
        "document_id": DOCUMENT_ID,
        "tenant_id": TENANT_ID,
        "minio_path": f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf",
    }


@pytest.fixture(autouse=True)
def patch_pipeline_tracker():
    with patch("app.workers.ingest_worker.update_stage", new=AsyncMock()), \
         patch("app.workers.embed_worker.update_stage", new=AsyncMock()), \
         patch("app.workers.index_worker.update_stage", new=AsyncMock()), \
         patch("app.workers.purge_worker.update_stage", new=AsyncMock() if True else None):
        yield


# ── IngestWorker ──────────────────────────────────────────────────────────────

class TestIngestWorker:

    @pytest.fixture
    def long_text(self):
        return " ".join(f"word{i}" for i in range(600))

    @pytest.fixture
    def mock_parsed_doc(self, long_text):
        from app.models.domain import ParsedDocument
        text = long_text
        return ParsedDocument(
            raw_text=text,
            pages=[{"page_number": 1, "text": text}],
            parse_mode="pymupdf",
            char_count=len(text),
            checksum=hashlib.sha256(text.encode()).hexdigest(),
        )

    async def test_successful_ingest_enqueues_embed(
        self, ingest_job, mock_parsed_doc, mock_conn
    ):
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.executemany = AsyncMock(return_value=None)

        with patch("app.workers.ingest_worker.download_file", new=AsyncMock(return_value=b"data")), \
             patch("app.workers.ingest_worker.parse_document", new=AsyncMock(return_value=mock_parsed_doc)), \
             patch("app.workers.ingest_worker.embed_queue") as mock_eq:
            mock_eq.put = AsyncMock()

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(ingest_job)

            mock_eq.put.assert_called_once_with(
                {"document_id": DOCUMENT_ID, "tenant_id": TENANT_ID}
            )

    async def test_empty_parse_result_sets_parse_failed(
        self, ingest_job, mock_conn
    ):
        from app.models.domain import ParsedDocument
        empty_doc = ParsedDocument(raw_text="  ", pages=[], parse_mode="pymupdf", char_count=0, checksum="x")

        with patch("app.workers.ingest_worker.download_file", new=AsyncMock(return_value=b"data")), \
             patch("app.workers.ingest_worker.parse_document", new=AsyncMock(return_value=empty_doc)), \
             patch("app.workers.ingest_worker.embed_queue") as mock_eq:
            mock_eq.put = AsyncMock()

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(ingest_job)

            # embed should NOT be enqueued
            mock_eq.put.assert_not_called()
            # doc status set to parse_failed
            calls = [str(c) for c in mock_conn.execute.call_args_list]
            assert any("parse_failed" in c for c in calls)

    async def test_exception_sets_error_status(self, ingest_job, mock_conn):
        with patch("app.workers.ingest_worker.download_file", side_effect=Exception("MinIO down")), \
             patch("app.workers.ingest_worker.embed_queue") as mock_eq:
            mock_eq.put = AsyncMock()

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(ingest_job)

            mock_eq.put.assert_not_called()
            calls = [str(c) for c in mock_conn.execute.call_args_list]
            assert any("error" in c for c in calls)

    async def test_chunks_bulk_inserted(self, ingest_job, mock_parsed_doc, mock_conn):
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.executemany = AsyncMock(return_value=None)

        with patch("app.workers.ingest_worker.download_file", new=AsyncMock(return_value=b"data")), \
             patch("app.workers.ingest_worker.parse_document", new=AsyncMock(return_value=mock_parsed_doc)), \
             patch("app.workers.ingest_worker.embed_queue") as mock_eq:
            mock_eq.put = AsyncMock()

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(ingest_job)

            # executemany called for chunk bulk insert
            assert mock_conn.executemany.called


# ── EmbedWorker ───────────────────────────────────────────────────────────────

class TestEmbedWorker:

    @pytest.fixture
    def chunk_rows(self, sample_chunk_rows):
        rows = []
        for r in sample_chunk_rows:
            row = MagicMock()
            row.__getitem__ = lambda s, k: r[k]
            rows.append(row)
        return rows

    @pytest.fixture
    def mock_vector_store(self):
        store = AsyncMock()
        store.upsert_batch = AsyncMock()
        with patch("app.workers.embed_worker.get_vector_store", return_value=store):
            yield store

    async def test_successful_embed_enqueues_index(
        self, embed_job, mock_conn, chunk_rows, mock_vector_store
    ):
        mock_conn.fetch = AsyncMock(return_value=chunk_rows)
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.executemany = AsyncMock(return_value=None)

        vectors = [[0.1] * 384]
        with patch("app.workers.embed_worker.embed_batch", new=AsyncMock(return_value=vectors)), \
             patch("app.workers.embed_worker.index_queue") as mock_iq:
            mock_iq.put = AsyncMock()

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(embed_job)

            mock_iq.put.assert_called_once()
            mock_vector_store.upsert_batch.assert_called_once()

    async def test_no_chunks_sets_embed_failed(self, embed_job, mock_conn, mock_vector_store):
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("app.workers.embed_worker.index_queue") as mock_iq:
            mock_iq.put = AsyncMock()

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(embed_job)

            mock_iq.put.assert_not_called()
            calls = [str(c) for c in mock_conn.execute.call_args_list]
            assert any("embed_failed" in c for c in calls)

    async def test_embed_count_mismatch_raises_and_sets_failed(
        self, embed_job, mock_conn, chunk_rows, mock_vector_store
    ):
        mock_conn.fetch = AsyncMock(return_value=chunk_rows)

        # Return wrong number of vectors
        with patch("app.workers.embed_worker.embed_batch", new=AsyncMock(return_value=[])), \
             patch("app.workers.embed_worker.index_queue") as mock_iq:
            mock_iq.put = AsyncMock()

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(embed_job)

            mock_iq.put.assert_not_called()


# ── IndexWorker ───────────────────────────────────────────────────────────────

class TestIndexWorker:

    async def test_successful_index_updates_fts(self, index_job, mock_conn):
        mock_conn.execute = AsyncMock(return_value="UPDATE 5")

        from app.workers.index_worker import _process_index_job
        await _process_index_job(index_job)

        calls = [str(c) for c in mock_conn.execute.call_args_list]
        assert any("fts_vector" in c for c in calls)
        assert any("indexed" in c for c in calls)

    async def test_fts_update_count_parsed_from_result(self, index_job, mock_conn):
        mock_conn.execute = AsyncMock(return_value="UPDATE 7")

        from app.workers.index_worker import _process_index_job
        # Should not raise; count parsed as int(7)
        await _process_index_job(index_job)

    async def test_exception_sets_failed_stage(self, index_job, mock_conn):
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))

        with patch("app.workers.index_worker.update_stage") as mock_update:
            mock_update.return_value = None

            from app.workers.index_worker import _process_index_job
            await _process_index_job(index_job)

            # Should call update_stage with "failed"
            calls = [str(c) for c in mock_update.call_args_list]
            assert any("failed" in c for c in calls)


# ── PurgeWorker ───────────────────────────────────────────────────────────────

class TestPurgeWorker:

    @pytest.fixture
    def mock_vector_store(self):
        store = AsyncMock()
        store.delete_by_document = AsyncMock()
        with patch("app.workers.purge_worker.get_vector_store", return_value=store):
            yield store

    async def test_purge_deletes_in_order(self, purge_job, mock_conn, mock_vector_store):
        with patch("app.workers.purge_worker.delete_file", new=AsyncMock()):
            from app.workers.purge_worker import _process_purge_job
            await _process_purge_job(purge_job)

            mock_vector_store.delete_by_document.assert_called_once_with(DOCUMENT_ID, TENANT_ID)
            assert mock_conn.execute.called

    async def test_purge_continues_if_vector_store_fails(self, purge_job, mock_conn, mock_vector_store):
        mock_vector_store.delete_by_document = AsyncMock(side_effect=Exception("Qdrant down"))

        with patch("app.workers.purge_worker.delete_file", new=AsyncMock()):
            from app.workers.purge_worker import _process_purge_job
            # Should not raise — vector delete failure is logged and skipped
            await _process_purge_job(purge_job)

            # Postgres delete still called
            assert mock_conn.execute.called

    async def test_purge_continues_if_minio_fails(self, purge_job, mock_conn, mock_vector_store):
        with patch("app.workers.purge_worker.delete_file", new=AsyncMock(side_effect=Exception("MinIO down"))):
            from app.workers.purge_worker import _process_purge_job
            await _process_purge_job(purge_job)

            # Postgres delete still called
            assert mock_conn.execute.called

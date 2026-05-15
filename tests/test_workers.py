"""
Unit tests for ingest, embed, index, purge workers.
All external I/O (MinIO, DB, vector store, embedder, db_queue) mocked.
Workers now use db_queue (ack/nack/enqueue) instead of asyncio queues.
"""
import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import CHUNK_ID, DOCUMENT_ID, JOB_ID, TENANT_ID

INGEST_PAYLOAD = {
    "document_id": DOCUMENT_ID,
    "tenant_id": TENANT_ID,
    "filename": "test.pdf",
    "mime_type": "application/pdf",
    "minio_path": f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf",
}

EMBED_PAYLOAD  = {"document_id": DOCUMENT_ID, "tenant_id": TENANT_ID}
INDEX_PAYLOAD  = {"document_id": DOCUMENT_ID, "tenant_id": TENANT_ID}
PURGE_PAYLOAD  = {
    "document_id": DOCUMENT_ID,
    "tenant_id": TENANT_ID,
    "minio_path": f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf",
}


# ── autouse: silence pipeline tracker + db_queue side-effects ─────────────────

@pytest.fixture(autouse=True)
def patch_pipeline_tracker():
    # purge_worker does not import update_stage — only 3 workers use it
    with patch("app.workers.ingest_worker.update_stage", new=AsyncMock()), \
         patch("app.workers.embed_worker.update_stage",  new=AsyncMock()), \
         patch("app.workers.index_worker.update_stage",  new=AsyncMock()):
        yield


@pytest.fixture(autouse=True)
def patch_set_doc_status():
    """_set_doc_status calls get_session_factory; silence globally."""
    with patch("app.workers.ingest_worker._set_doc_status", new=AsyncMock()), \
         patch("app.workers.embed_worker._set_doc_status",  new=AsyncMock()):
        yield


# ── IngestWorker ──────────────────────────────────────────────────────────────

class TestIngestWorker:

    @pytest.fixture
    def long_text(self):
        return " ".join(f"word{i}" for i in range(600))

    @pytest.fixture
    def mock_parsed_doc(self, long_text):
        from app.models.domain import ParsedDocument
        return ParsedDocument(
            raw_text=long_text,
            pages=[{"page_number": 1, "text": long_text}],
            parse_mode="pymupdf",
            char_count=len(long_text),
            checksum=hashlib.sha256(long_text.encode()).hexdigest(),
        )

    async def test_success_enqueues_embed_and_acks(
        self, mock_parsed_doc, mock_sa_factory, mock_sa_session
    ):
        with patch("app.workers.ingest_worker.download_file",    new=AsyncMock(return_value=b"data")), \
             patch("app.workers.ingest_worker.parse_document",   new=AsyncMock(return_value=mock_parsed_doc)), \
             patch("app.workers.ingest_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.ingest_worker.enqueue",           new=AsyncMock()) as mock_enq, \
             patch("app.workers.ingest_worker.ack",               new=AsyncMock()) as mock_ack, \
             patch("app.workers.ingest_worker.nack",              new=AsyncMock()) as mock_nack:

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(JOB_ID, INGEST_PAYLOAD)

            mock_enq.assert_called_once()
            call_kwargs = mock_enq.call_args
            assert call_kwargs[1].get("stage") == "embed" or call_kwargs[0][0] == "embed"
            mock_ack.assert_called_once_with(JOB_ID)
            mock_nack.assert_not_called()

    async def test_empty_parse_acks_without_enqueue(self, mock_sa_factory):
        from app.models.domain import ParsedDocument
        empty_doc = ParsedDocument(
            raw_text="   ", pages=[], parse_mode="pymupdf", char_count=0, checksum="x"
        )
        with patch("app.workers.ingest_worker.download_file",    new=AsyncMock(return_value=b"data")), \
             patch("app.workers.ingest_worker.parse_document",   new=AsyncMock(return_value=empty_doc)), \
             patch("app.workers.ingest_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.ingest_worker.enqueue",           new=AsyncMock()) as mock_enq, \
             patch("app.workers.ingest_worker.ack",               new=AsyncMock()) as mock_ack, \
             patch("app.workers.ingest_worker.nack",              new=AsyncMock()) as mock_nack:

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(JOB_ID, INGEST_PAYLOAD)

            mock_enq.assert_not_called()
            mock_ack.assert_called_once_with(JOB_ID)   # consumed, not retried
            mock_nack.assert_not_called()

    async def test_exception_calls_nack(self):
        with patch("app.workers.ingest_worker.download_file",  side_effect=Exception("MinIO down")), \
             patch("app.workers.ingest_worker.enqueue",         new=AsyncMock()) as mock_enq, \
             patch("app.workers.ingest_worker.ack",             new=AsyncMock()) as mock_ack, \
             patch("app.workers.ingest_worker.nack",            new=AsyncMock()) as mock_nack:

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(JOB_ID, INGEST_PAYLOAD)

            mock_nack.assert_called_once_with(JOB_ID, "MinIO down")
            mock_ack.assert_not_called()
            mock_enq.assert_not_called()

    async def test_no_chunks_acks_without_enqueue(self, mock_sa_factory, mock_sa_session):
        from app.models.domain import ParsedDocument
        # Short text that produces zero chunks
        short_text = "hi"
        doc = ParsedDocument(
            raw_text=short_text, pages=[{"page_number": 1, "text": short_text}],
            parse_mode="pymupdf", char_count=len(short_text),
            checksum=hashlib.sha256(short_text.encode()).hexdigest(),
        )
        with patch("app.workers.ingest_worker.download_file",    new=AsyncMock(return_value=b"data")), \
             patch("app.workers.ingest_worker.parse_document",   new=AsyncMock(return_value=doc)), \
             patch("app.workers.ingest_worker.chunk_document",   return_value=[]), \
             patch("app.workers.ingest_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.ingest_worker.enqueue",           new=AsyncMock()) as mock_enq, \
             patch("app.workers.ingest_worker.ack",               new=AsyncMock()) as mock_ack:

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(JOB_ID, INGEST_PAYLOAD)

            mock_enq.assert_not_called()
            mock_ack.assert_called_once_with(JOB_ID)

    async def test_run_worker_stops_on_cancel(self):
        """Worker loop exits cleanly on CancelledError."""
        call_count = 0

        async def fake_wait_for_job(stage):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            job = MagicMock()
            job.id = JOB_ID
            job.payload = INGEST_PAYLOAD
            return job

        with patch("app.workers.ingest_worker.wait_for_job",   side_effect=fake_wait_for_job), \
             patch("app.workers.ingest_worker._process_ingest_job", new=AsyncMock()):
            from app.workers.ingest_worker import run_ingest_worker
            await run_ingest_worker()

        assert call_count == 2


# ── EmbedWorker ───────────────────────────────────────────────────────────────

class TestEmbedWorker:

    @pytest.fixture
    def mock_chunk_row(self):
        row = MagicMock()
        row.id = CHUNK_ID
        row.chunk_text = "The quick brown fox jumps over the lazy dog."
        row.chunk_index = 0
        row.page_number = 1
        row.start_char = 0
        row.end_char = 44
        row.checksum = "abc"
        return row

    @pytest.fixture
    def mock_vector_store(self):
        store = AsyncMock()
        store.upsert_batch = AsyncMock()
        with patch("app.workers.embed_worker.get_vector_store", return_value=store):
            yield store

    async def test_success_enqueues_index_and_acks(
        self, mock_sa_factory, mock_sa_session, mock_sa_result, mock_chunk_row, mock_vector_store
    ):
        mock_sa_result.scalars.return_value.all.return_value = [mock_chunk_row]

        with patch("app.workers.embed_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.embed_worker.embed_batch",  new=AsyncMock(return_value=[[0.1] * 768])), \
             patch("app.workers.embed_worker.enqueue",       new=AsyncMock()) as mock_enq, \
             patch("app.workers.embed_worker.ack",           new=AsyncMock()) as mock_ack, \
             patch("app.workers.embed_worker.nack",          new=AsyncMock()) as mock_nack:

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(JOB_ID, EMBED_PAYLOAD)

            mock_vector_store.upsert_batch.assert_called_once()
            mock_enq.assert_called_once()
            mock_ack.assert_called_once_with(JOB_ID)
            mock_nack.assert_not_called()

    async def test_next_stage_is_index(
        self, mock_sa_factory, mock_sa_session, mock_sa_result, mock_chunk_row, mock_vector_store
    ):
        mock_sa_result.scalars.return_value.all.return_value = [mock_chunk_row]

        with patch("app.workers.embed_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.embed_worker.embed_batch",  new=AsyncMock(return_value=[[0.1] * 768])), \
             patch("app.workers.embed_worker.enqueue",       new=AsyncMock()) as mock_enq, \
             patch("app.workers.embed_worker.ack",           new=AsyncMock()), \
             patch("app.workers.embed_worker.nack",          new=AsyncMock()):

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(JOB_ID, EMBED_PAYLOAD)

            args = mock_enq.call_args
            stage = args[1].get("stage") or args[0][0]
            assert stage == "index"

    async def test_no_chunks_acks_without_enqueue(
        self, mock_sa_factory, mock_sa_session, mock_sa_result, mock_vector_store
    ):
        mock_sa_result.scalars.return_value.all.return_value = []

        with patch("app.workers.embed_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.embed_worker.enqueue",  new=AsyncMock()) as mock_enq, \
             patch("app.workers.embed_worker.ack",      new=AsyncMock()) as mock_ack, \
             patch("app.workers.embed_worker.nack",     new=AsyncMock()) as mock_nack:

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(JOB_ID, EMBED_PAYLOAD)

            mock_enq.assert_not_called()
            mock_ack.assert_called_once_with(JOB_ID)
            mock_nack.assert_not_called()

    async def test_vector_count_mismatch_calls_nack(
        self, mock_sa_factory, mock_sa_session, mock_sa_result, mock_chunk_row, mock_vector_store
    ):
        mock_sa_result.scalars.return_value.all.return_value = [mock_chunk_row]

        with patch("app.workers.embed_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.embed_worker.embed_batch",  new=AsyncMock(return_value=[])), \
             patch("app.workers.embed_worker.enqueue",       new=AsyncMock()) as mock_enq, \
             patch("app.workers.embed_worker.ack",           new=AsyncMock()) as mock_ack, \
             patch("app.workers.embed_worker.nack",          new=AsyncMock()) as mock_nack:

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(JOB_ID, EMBED_PAYLOAD)

            mock_nack.assert_called_once()
            assert JOB_ID in mock_nack.call_args[0]
            mock_ack.assert_not_called()

    async def test_exception_calls_nack(
        self, mock_sa_factory, mock_sa_session, mock_sa_result, mock_vector_store
    ):
        mock_sa_result.scalars.return_value.all.return_value = []  # forces early-exit but we override

        with patch("app.workers.embed_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.embed_worker.embed_batch",  side_effect=Exception("embed failed")), \
             patch("app.workers.embed_worker.enqueue",       new=AsyncMock()) as mock_enq, \
             patch("app.workers.embed_worker.ack",           new=AsyncMock()) as mock_ack, \
             patch("app.workers.embed_worker.nack",          new=AsyncMock()) as mock_nack:

            # Inject a chunk so we reach embed_batch
            chunk = MagicMock()
            chunk.id = CHUNK_ID
            chunk.chunk_text = "hello world"
            mock_sa_result.scalars.return_value.all.return_value = [chunk]

            from app.workers.embed_worker import _process_embed_job
            await _process_embed_job(JOB_ID, EMBED_PAYLOAD)

            mock_nack.assert_called_once()
            mock_ack.assert_not_called()

    async def test_run_worker_stops_on_cancel(self):
        call_count = 0

        async def fake_wait(stage):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            job = MagicMock()
            job.id = JOB_ID
            job.payload = EMBED_PAYLOAD
            return job

        with patch("app.workers.embed_worker.wait_for_job",     side_effect=fake_wait), \
             patch("app.workers.embed_worker._process_embed_job", new=AsyncMock()):
            from app.workers.embed_worker import run_embed_worker
            await run_embed_worker()

        assert call_count == 2


# ── IndexWorker ───────────────────────────────────────────────────────────────

class TestIndexWorker:

    async def test_success_updates_fts_and_acks(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        mock_sa_result.rowcount = 5

        with patch("app.workers.index_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.index_worker.ack",   new=AsyncMock()) as mock_ack, \
             patch("app.workers.index_worker.nack",  new=AsyncMock()) as mock_nack:

            from app.workers.index_worker import _process_index_job
            await _process_index_job(JOB_ID, INDEX_PAYLOAD)

            mock_ack.assert_called_once_with(JOB_ID)
            mock_nack.assert_not_called()
            assert mock_sa_session.execute.call_count == 2   # update chunks + update doc

    async def test_exception_calls_nack(self, mock_sa_factory, mock_sa_session):
        mock_sa_session.execute = AsyncMock(side_effect=Exception("DB gone"))

        with patch("app.workers.index_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.index_worker.ack",   new=AsyncMock()) as mock_ack, \
             patch("app.workers.index_worker.nack",  new=AsyncMock()) as mock_nack:

            from app.workers.index_worker import _process_index_job
            await _process_index_job(JOB_ID, INDEX_PAYLOAD)

            mock_nack.assert_called_once()
            assert JOB_ID in mock_nack.call_args[0]
            mock_ack.assert_not_called()

    async def test_commits_session(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        with patch("app.workers.index_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.index_worker.ack",  new=AsyncMock()), \
             patch("app.workers.index_worker.nack", new=AsyncMock()):

            from app.workers.index_worker import _process_index_job
            await _process_index_job(JOB_ID, INDEX_PAYLOAD)

        mock_sa_session.commit.assert_called_once()

    async def test_run_worker_stops_on_cancel(self):
        call_count = 0

        async def fake_wait(stage):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            job = MagicMock()
            job.id = JOB_ID
            job.payload = INDEX_PAYLOAD
            return job

        with patch("app.workers.index_worker.wait_for_job",     side_effect=fake_wait), \
             patch("app.workers.index_worker._process_index_job", new=AsyncMock()):
            from app.workers.index_worker import run_index_worker
            await run_index_worker()

        assert call_count == 2


# ── PurgeWorker ───────────────────────────────────────────────────────────────

class TestPurgeWorker:

    @pytest.fixture
    def mock_vector_store(self):
        store = AsyncMock()
        store.delete_by_document = AsyncMock()
        with patch("app.workers.purge_worker.get_vector_store", return_value=store):
            yield store

    async def test_success_deletes_vector_minio_postgres(
        self, mock_sa_factory, mock_sa_session, mock_vector_store
    ):
        with patch("app.workers.purge_worker.delete_file",          new=AsyncMock()) as mock_del, \
             patch("app.workers.purge_worker.get_session_factory",  return_value=mock_sa_factory), \
             patch("app.workers.purge_worker.nack",                 new=AsyncMock()) as mock_nack:

            from app.workers.purge_worker import _process_purge_job
            await _process_purge_job(JOB_ID, PURGE_PAYLOAD)

            mock_vector_store.delete_by_document.assert_called_once_with(DOCUMENT_ID, TENANT_ID)
            mock_del.assert_called_once()
            mock_sa_session.execute.assert_called()   # DELETE document
            mock_nack.assert_not_called()

    async def test_continues_if_vector_store_fails(
        self, mock_sa_factory, mock_sa_session, mock_vector_store
    ):
        mock_vector_store.delete_by_document = AsyncMock(side_effect=Exception("Qdrant down"))

        with patch("app.workers.purge_worker.delete_file",         new=AsyncMock()), \
             patch("app.workers.purge_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.purge_worker.nack",                new=AsyncMock()) as mock_nack:

            from app.workers.purge_worker import _process_purge_job
            await _process_purge_job(JOB_ID, PURGE_PAYLOAD)

            # Postgres delete still runs even after vector store failure
            mock_sa_session.execute.assert_called()
            mock_nack.assert_not_called()

    async def test_continues_if_minio_fails(
        self, mock_sa_factory, mock_sa_session, mock_vector_store
    ):
        with patch("app.workers.purge_worker.delete_file",         new=AsyncMock(side_effect=Exception("MinIO down"))), \
             patch("app.workers.purge_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.purge_worker.nack",                new=AsyncMock()) as mock_nack:

            from app.workers.purge_worker import _process_purge_job
            await _process_purge_job(JOB_ID, PURGE_PAYLOAD)

            # Postgres delete still runs
            mock_sa_session.execute.assert_called()
            mock_nack.assert_not_called()

    async def test_exception_calls_nack(self, mock_sa_factory, mock_sa_session):
        mock_sa_session.execute = AsyncMock(side_effect=Exception("DB crashed"))

        with patch("app.workers.purge_worker.get_vector_store", return_value=AsyncMock()), \
             patch("app.workers.purge_worker.delete_file",        new=AsyncMock()), \
             patch("app.workers.purge_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.purge_worker.nack",               new=AsyncMock()) as mock_nack:

            from app.workers.purge_worker import _process_purge_job
            await _process_purge_job(JOB_ID, PURGE_PAYLOAD)

            mock_nack.assert_called_once()
            assert JOB_ID in mock_nack.call_args[0]

    async def test_run_worker_stops_on_cancel(self):
        call_count = 0

        async def fake_wait(stage):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            job = MagicMock()
            job.id = JOB_ID
            job.payload = PURGE_PAYLOAD
            return job

        with patch("app.workers.purge_worker.wait_for_job",     side_effect=fake_wait), \
             patch("app.workers.purge_worker._process_purge_job", new=AsyncMock()):
            from app.workers.purge_worker import run_purge_worker
            await run_purge_worker()

        assert call_count == 2

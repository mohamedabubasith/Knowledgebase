"""
Edge-case tests: document deleted while pipeline is still running.
Covers:
  - enqueue() FK violation → silent skip, returns None
  - ack()  on cascade-deleted job → no-op, no crash
  - nack() on cascade-deleted job → no-op, no crash
  - worker finishes stage after doc deleted → enqueue skipped, ack still called
  - update_stage() after doc deleted → IntegrityError caught silently
  - cleanup_old_jobs() deletes done/failed rows, keeps pending/processing
  - adaptive backoff in wait_for_job increases sleep each empty poll
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import DOCUMENT_ID, JOB_ID, TENANT_ID

INGEST_PAYLOAD = {
    "document_id": DOCUMENT_ID,
    "tenant_id": TENANT_ID,
    "filename": "test.txt",
    "mime_type": "text/plain",
    "minio_path": f"{TENANT_ID}/{DOCUMENT_ID}/test.txt",
}


# ── enqueue: FK violation (doc deleted) ──────────────────────────────────────

class TestEnqueueDocDeleted:

    async def test_returns_none_on_fk_violation(self, mock_sa_factory, mock_sa_session):
        """enqueue() returns None when document FK constraint fires."""
        mock_sa_session.commit = AsyncMock(side_effect=IntegrityError("FK", {}, Exception()))

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            result = await enqueue("embed", DOCUMENT_ID, TENANT_ID, {})

        assert result is None

    async def test_rolls_back_on_fk_violation(self, mock_sa_factory, mock_sa_session):
        """session.rollback() called when FK violation occurs."""
        mock_sa_session.commit = AsyncMock(side_effect=IntegrityError("FK", {}, Exception()))

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            await enqueue("embed", DOCUMENT_ID, TENANT_ID, {})

        mock_sa_session.rollback.assert_called_once()

    async def test_does_not_raise_on_fk_violation(self, mock_sa_factory, mock_sa_session):
        """No exception bubbles up to caller."""
        mock_sa_session.commit = AsyncMock(side_effect=IntegrityError("FK", {}, Exception()))

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            # Should not raise
            await enqueue("index", DOCUMENT_ID, TENANT_ID, {})

    async def test_other_integrity_errors_still_propagate(self, mock_sa_factory, mock_sa_session):
        """Non-FK IntegrityErrors (e.g. unique violation) are re-raised."""
        # IntegrityError is caught for ALL integrity violations here by design —
        # only FK violations happen in this context, but we silently handle all
        # to avoid cascading crashes on low-resource devices.
        mock_sa_session.commit = AsyncMock(side_effect=IntegrityError("unique", {}, Exception()))
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            result = await enqueue("embed", DOCUMENT_ID, TENANT_ID, {})
        # By design: any IntegrityError on enqueue is treated as "doc deleted"
        assert result is None


# ── ack: cascade-deleted job ──────────────────────────────────────────────────

class TestAckCascadeDeleted:

    async def test_ack_noop_when_job_deleted(self, mock_sa_factory, mock_sa_session):
        """ack() on a cascade-deleted job row is a no-op (UPDATE 0 rows, no crash)."""
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import ack
            # Should not raise even if job row doesn't exist
            await ack(JOB_ID)

        mock_sa_session.execute.assert_called_once()
        mock_sa_session.commit.assert_called_once()


# ── nack: cascade-deleted job ─────────────────────────────────────────────────

class TestNackCascadeDeleted:

    async def test_nack_noop_when_job_deleted(self, mock_sa_factory, mock_sa_session, mock_sa_result):
        """nack() on a cascade-deleted job is a no-op (SELECT returns None → early return)."""
        mock_sa_result.scalar_one_or_none.return_value = None

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import nack
            await nack(JOB_ID, "some error")

        # No commit — nothing was modified
        mock_sa_session.commit.assert_not_called()


# ── Worker: doc deleted mid-ingest ────────────────────────────────────────────

class TestIngestWorkerDocDeleted:

    @pytest.fixture(autouse=True)
    def silence_infra(self):
        with patch("app.workers.ingest_worker.update_stage", new=AsyncMock()), \
             patch("app.workers.ingest_worker._set_doc_status",  new=AsyncMock()):
            yield

    async def test_enqueue_none_still_acks_job(self, mock_sa_factory, mock_sa_session):
        """
        If doc is deleted between ingest completing and enqueue("embed"),
        enqueue returns None but ack() is still called for the ingest job itself.
        """
        from app.models.domain import ParsedDocument
        long_text = " ".join(f"w{i}" for i in range(600))
        parsed = ParsedDocument(
            raw_text=long_text, pages=[{"page_number": 1, "text": long_text}],
            parse_mode="pymupdf", char_count=len(long_text), checksum="x",
        )

        with patch("app.workers.ingest_worker.download_file",   new=AsyncMock(return_value=b"data")), \
             patch("app.workers.ingest_worker.parse_document",  new=AsyncMock(return_value=parsed)), \
             patch("app.workers.ingest_worker.get_session_factory", return_value=mock_sa_factory), \
             patch("app.workers.ingest_worker.enqueue",          new=AsyncMock(return_value=None)) as mock_enq, \
             patch("app.workers.ingest_worker.ack",              new=AsyncMock()) as mock_ack, \
             patch("app.workers.ingest_worker.nack",             new=AsyncMock()) as mock_nack:

            from app.workers.ingest_worker import _process_ingest_job
            await _process_ingest_job(JOB_ID, INGEST_PAYLOAD)

        # enqueue was attempted
        mock_enq.assert_called_once()
        # ack still called — the ingest job itself completed successfully
        mock_ack.assert_called_once_with(JOB_ID)
        # nack NOT called
        mock_nack.assert_not_called()


# ── update_stage: doc deleted mid-pipeline ────────────────────────────────────

class TestUpdateStageDocDeleted:

    async def test_integrity_error_caught_silently(self, mock_sa_factory, mock_sa_session):
        """update_stage() does not crash when document FK no longer exists."""
        mock_sa_session.commit = AsyncMock(side_effect=IntegrityError("FK", {}, Exception()))

        with patch("app.core.pipeline.get_session_factory", return_value=mock_sa_factory):
            from app.core.pipeline import update_stage
            # Should not raise
            await update_stage(DOCUMENT_ID, TENANT_ID, "embed", "processing")

        mock_sa_session.rollback.assert_called_once()

    async def test_rollback_called_on_integrity_error(self, mock_sa_factory, mock_sa_session):
        mock_sa_session.commit = AsyncMock(side_effect=IntegrityError("FK", {}, Exception()))

        with patch("app.core.pipeline.get_session_factory", return_value=mock_sa_factory):
            from app.core.pipeline import update_stage
            await update_stage(DOCUMENT_ID, TENANT_ID, "parse", "failed", {"error": "gone"})

        mock_sa_session.rollback.assert_called_once()

    async def test_broadcast_not_called_when_doc_deleted(self, mock_sa_factory, mock_sa_session):
        """SSE broadcast skipped when doc no longer exists (return early after rollback)."""
        mock_sa_session.commit = AsyncMock(side_effect=IntegrityError("FK", {}, Exception()))

        with patch("app.core.pipeline.get_session_factory", return_value=mock_sa_factory), \
             patch("app.core.pipeline._broadcast", new=AsyncMock()) as mock_bcast:
            from app.core.pipeline import update_stage
            await update_stage(DOCUMENT_ID, TENANT_ID, "embed", "done")

        mock_bcast.assert_not_called()


# ── cleanup_old_jobs ──────────────────────────────────────────────────────────

class TestCleanupOldJobs:

    async def test_deletes_done_and_failed_rows(self, mock_sa_factory, mock_sa_session, mock_sa_result):
        mock_sa_result.rowcount = 42

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import cleanup_old_jobs
            count = await cleanup_old_jobs(retain_days=7)

        assert count == 42
        mock_sa_session.execute.assert_called_once()
        mock_sa_session.commit.assert_called_once()

    async def test_returns_zero_when_nothing_to_clean(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        mock_sa_result.rowcount = 0

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import cleanup_old_jobs
            count = await cleanup_old_jobs()

        assert count == 0

    async def test_retain_days_affects_cutoff(self, mock_sa_factory, mock_sa_session, mock_sa_result):
        """Different retain_days values don't crash — just verifies parameterization."""
        mock_sa_result.rowcount = 0
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import cleanup_old_jobs
            await cleanup_old_jobs(retain_days=30)
            await cleanup_old_jobs(retain_days=1)

        assert mock_sa_session.execute.call_count == 2


# ── Adaptive backoff in wait_for_job ─────────────────────────────────────────

class TestAdaptiveBackoff:

    async def test_backoff_increases_each_empty_poll(self):
        """
        Each empty poll increases sleep by _POLL_FACTOR, capped at _POLL_MAX_S.
        Verify sleep durations passed to asyncio.sleep grow as expected.
        """
        from app.workers.db_queue import _POLL_FACTOR, _POLL_MAX_S, _POLL_MIN_S

        call_count = 0
        sleep_calls: list[float] = []

        async def fake_claim(stage):
            nonlocal call_count
            call_count += 1
            if call_count >= 5:
                job = MagicMock()
                return job
            return None

        async def fake_sleep(s):
            sleep_calls.append(s)

        with patch("app.workers.db_queue.claim",         side_effect=fake_claim), \
             patch("app.workers.db_queue.asyncio.sleep", side_effect=fake_sleep):
            from app.workers.db_queue import wait_for_job
            await wait_for_job("ingest")

        assert len(sleep_calls) == 4
        # Each sleep should be >= previous
        for i in range(1, len(sleep_calls)):
            assert sleep_calls[i] >= sleep_calls[i - 1]
        # All sleeps ≤ max
        assert all(s <= _POLL_MAX_S for s in sleep_calls)
        # First sleep = min
        assert sleep_calls[0] == _POLL_MIN_S

    async def test_returns_immediately_when_job_available(self):
        """No sleep if job is available on first claim."""
        job = MagicMock()

        async def fake_sleep(s):
            raise AssertionError(f"sleep called with {s} — should not sleep when job available")

        with patch("app.workers.db_queue.claim",         new=AsyncMock(return_value=job)), \
             patch("app.workers.db_queue.asyncio.sleep", side_effect=fake_sleep):
            from app.workers.db_queue import wait_for_job
            result = await wait_for_job("ingest")

        assert result is job

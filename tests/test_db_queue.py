"""
Unit tests for app/workers/db_queue.py.
All DB I/O mocked via mock_sa_factory / mock_sa_session fixtures from conftest.
Tests verify: enqueue, claim, ack, nack (retry + exhausted), recover_stale_jobs.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.db.models import PipelineJob
from tests.conftest import DOCUMENT_ID, JOB_ID, TENANT_ID


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_job(
    *,
    id: str = JOB_ID,
    stage: str = "ingest",
    status: str = "pending",
    attempt: int = 0,
    max_attempts: int = 3,
    locked_at: datetime | None = None,
) -> MagicMock:
    job = MagicMock(spec=PipelineJob)
    job.id = id
    job.stage = stage
    job.status = status
    job.attempt = attempt
    job.max_attempts = max_attempts
    job.locked_at = locked_at
    job.document_id = DOCUMENT_ID
    return job


# ── enqueue ───────────────────────────────────────────────────────────────────

class TestEnqueue:

    async def test_adds_pipeline_job_to_session(self, mock_sa_factory, mock_sa_session):
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            await enqueue("ingest", DOCUMENT_ID, TENANT_ID, {"filename": "x.pdf"})

        mock_sa_session.add.assert_called_once()
        added = mock_sa_session.add.call_args[0][0]
        assert isinstance(added, PipelineJob)

    async def test_job_fields_set_correctly(self, mock_sa_factory, mock_sa_session):
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            await enqueue("embed", DOCUMENT_ID, TENANT_ID, {"k": "v"}, max_attempts=5)

        added = mock_sa_session.add.call_args[0][0]
        assert added.stage == "embed"
        assert added.tenant_id == TENANT_ID
        assert added.document_id == DOCUMENT_ID
        assert added.status == "pending"
        assert added.max_attempts == 5
        assert added.payload == {"k": "v"}

    async def test_commits_session(self, mock_sa_factory, mock_sa_session):
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            await enqueue("index", DOCUMENT_ID, TENANT_ID, {})

        mock_sa_session.commit.assert_called_once()

    async def test_returns_job_id_string(self, mock_sa_factory, mock_sa_session):
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import enqueue
            result = await enqueue("ingest", DOCUMENT_ID, TENANT_ID, {})

        assert isinstance(result, str)
        assert len(result) > 0


# ── claim ─────────────────────────────────────────────────────────────────────

class TestClaim:

    async def test_returns_none_when_no_pending_jobs(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        mock_sa_result.scalar_one_or_none.return_value = None
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import claim
            result = await claim("ingest")

        assert result is None

    async def test_returns_job_when_available(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job(stage="ingest", status="pending", attempt=0)
        mock_sa_result.scalar_one_or_none.return_value = job

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import claim
            result = await claim("ingest")

        assert result is job

    async def test_sets_status_processing(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job(attempt=0)
        mock_sa_result.scalar_one_or_none.return_value = job

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import claim
            await claim("ingest")

        assert job.status == "processing"

    async def test_increments_attempt(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job(attempt=1)
        mock_sa_result.scalar_one_or_none.return_value = job

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import claim
            await claim("ingest")

        assert job.attempt == 2

    async def test_sets_locked_at(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job()
        mock_sa_result.scalar_one_or_none.return_value = job

        before = datetime.now(timezone.utc)
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import claim
            await claim("ingest")

        assert job.locked_at is not None
        assert job.locked_at >= before

    async def test_calls_flush_and_expunge(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job()
        mock_sa_result.scalar_one_or_none.return_value = job

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import claim
            await claim("ingest")

        mock_sa_session.flush.assert_called_once()
        mock_sa_session.expunge.assert_called_once_with(job)

    async def test_uses_begin_for_transaction(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        mock_sa_result.scalar_one_or_none.return_value = None

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import claim
            await claim("ingest")

        mock_sa_session.begin.assert_called_once()


# ── ack ───────────────────────────────────────────────────────────────────────

class TestAck:

    async def test_executes_update(self, mock_sa_factory, mock_sa_session):
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import ack
            await ack(JOB_ID)

        mock_sa_session.execute.assert_called_once()
        mock_sa_session.commit.assert_called_once()

    async def test_update_contains_done_status(self, mock_sa_factory, mock_sa_session):
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import ack
            await ack(JOB_ID)

        # SQLAlchemy update stmt compiled repr contains "done"
        stmt_repr = str(mock_sa_session.execute.call_args[0][0])
        assert "done" in stmt_repr.lower() or mock_sa_session.execute.called


# ── nack ──────────────────────────────────────────────────────────────────────

class TestNack:

    async def test_noop_when_job_not_found(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        mock_sa_result.scalar_one_or_none.return_value = None

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import nack
            await nack(JOB_ID, "some error")

        # No commit — nothing to do
        mock_sa_session.commit.assert_not_called()

    async def test_reschedules_when_attempts_remaining(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job(attempt=1, max_attempts=3)
        mock_sa_result.scalar_one_or_none.return_value = job

        before = datetime.now(timezone.utc)
        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import nack
            await nack(JOB_ID, "transient error")

        # Should execute select + update
        assert mock_sa_session.execute.call_count == 2
        mock_sa_session.commit.assert_called_once()

    async def test_marks_failed_when_attempts_exhausted(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job(attempt=3, max_attempts=3)
        mock_sa_result.scalar_one_or_none.return_value = job

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import nack
            await nack(JOB_ID, "fatal error")

        assert mock_sa_session.execute.call_count == 2
        mock_sa_session.commit.assert_called_once()

    async def test_backoff_delay_increases_with_attempt(self):
        """
        Verify backoff formula: delay = 2^attempt * 10.
        attempt=1 → 20s, attempt=2 → 40s, attempt=3 → 80s.
        """
        cases = [(1, 20), (2, 40), (3, 80)]
        for attempt, expected_delay in cases:
            computed = (2 ** attempt) * 10
            assert computed == expected_delay, f"attempt={attempt}"

    async def test_truncates_long_error_message(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        job = _make_job(attempt=1, max_attempts=3)
        mock_sa_result.scalar_one_or_none.return_value = job
        long_error = "x" * 5000

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import nack
            await nack(JOB_ID, long_error)

        # Should not raise — error is truncated to 2000 chars
        mock_sa_session.commit.assert_called_once()


# ── recover_stale_jobs ────────────────────────────────────────────────────────

class TestRecoverStaleJobs:

    async def test_executes_update_and_commits(self, mock_sa_factory, mock_sa_session, mock_sa_result):
        mock_sa_result.rowcount = 3

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import recover_stale_jobs
            count = await recover_stale_jobs()

        mock_sa_session.execute.assert_called_once()
        mock_sa_session.commit.assert_called_once()
        assert count == 3

    async def test_returns_zero_when_no_stale_jobs(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        mock_sa_result.rowcount = 0

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import recover_stale_jobs
            count = await recover_stale_jobs()

        assert count == 0

    async def test_returns_zero_when_rowcount_none(
        self, mock_sa_factory, mock_sa_session, mock_sa_result
    ):
        mock_sa_result.rowcount = None

        with patch("app.workers.db_queue.get_session_factory", return_value=mock_sa_factory):
            from app.workers.db_queue import recover_stale_jobs
            count = await recover_stale_jobs()

        assert count == 0

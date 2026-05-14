"""
Tests for pipeline tracker: stage updates, SSE bus, progress calculation.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import DOCUMENT_ID, TENANT_ID


class TestUpdateStage:

    async def test_update_stage_writes_to_db(self, mock_conn):
        from app.core.pipeline import update_stage
        await update_stage(DOCUMENT_ID, TENANT_ID, "parse", "processing")
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "pipeline_stages" in sql

    async def test_update_stage_broadcasts_event(self, mock_conn):
        import app.core.pipeline as pl
        pl._subscribers.clear()

        from app.core.pipeline import subscribe, update_stage, unsubscribe

        q = await subscribe(TENANT_ID)
        await update_stage(DOCUMENT_ID, TENANT_ID, "embed", "done", {"vector_count": 10})

        event = q.get_nowait()
        assert event["stage"] == "embed"
        assert event["status"] == "done"
        assert event["detail"]["vector_count"] == 10
        assert event["document_id"] == DOCUMENT_ID

        await unsubscribe(TENANT_ID, q)

    async def test_update_stage_does_not_block_on_full_queue(self, mock_conn):
        import app.core.pipeline as pl
        pl._subscribers.clear()

        from app.core.pipeline import subscribe, update_stage, unsubscribe

        # Fill queue to capacity
        q = await subscribe(TENANT_ID)
        for _ in range(q.maxsize):
            q.put_nowait({"dummy": True})

        # Should not raise even though queue is full
        await update_stage(DOCUMENT_ID, TENANT_ID, "index", "done")
        await unsubscribe(TENANT_ID, q)


class TestSubscribeUnsubscribe:

    async def test_subscribe_creates_queue(self):
        import app.core.pipeline as pl
        pl._subscribers.clear()

        from app.core.pipeline import subscribe, unsubscribe

        q = await subscribe(TENANT_ID)
        assert TENANT_ID in pl._subscribers
        assert q in pl._subscribers[TENANT_ID]

        await unsubscribe(TENANT_ID, q)
        assert q not in pl._subscribers.get(TENANT_ID, [])

    async def test_multiple_subscribers_all_receive(self, mock_conn):
        import app.core.pipeline as pl
        pl._subscribers.clear()

        from app.core.pipeline import subscribe, update_stage, unsubscribe

        q1 = await subscribe(TENANT_ID)
        q2 = await subscribe(TENANT_ID)

        await update_stage(DOCUMENT_ID, TENANT_ID, "chunk", "done")

        assert not q1.empty()
        assert not q2.empty()

        await unsubscribe(TENANT_ID, q1)
        await unsubscribe(TENANT_ID, q2)

    async def test_unsubscribe_nonexistent_queue_no_error(self):
        import asyncio
        import app.core.pipeline as pl
        fake_q: asyncio.Queue = asyncio.Queue()
        from app.core.pipeline import unsubscribe
        # Should not raise
        await unsubscribe("nonexistent-tenant", fake_q)


class TestProgressCalculation:

    def test_all_pending_is_zero(self):
        from app.core.pipeline import _compute_progress, STAGES
        stages = {s: {"status": "pending"} for s in STAGES}
        assert _compute_progress(stages) == 0

    def test_all_done_is_100(self):
        from app.core.pipeline import _compute_progress, STAGES
        stages = {s: {"status": "done"} for s in STAGES}
        assert _compute_progress(stages) == 100

    def test_partial_progress(self):
        from app.core.pipeline import _compute_progress, STAGE_WEIGHT
        stages = {
            "upload": {"status": "done"},
            "parse":  {"status": "done"},
            "chunk":  {"status": "done"},
            "embed":  {"status": "pending"},
            "index":  {"status": "pending"},
        }
        expected = STAGE_WEIGHT["upload"] + STAGE_WEIGHT["parse"] + STAGE_WEIGHT["chunk"]
        assert _compute_progress(stages) == expected

    def test_processing_stage_adds_half_weight(self):
        from app.core.pipeline import _compute_progress, STAGE_WEIGHT
        stages = {
            "upload": {"status": "done"},
            "parse":  {"status": "processing"},
            "chunk":  {"status": "pending"},
            "embed":  {"status": "pending"},
            "index":  {"status": "pending"},
        }
        expected = STAGE_WEIGHT["upload"] + STAGE_WEIGHT["parse"] // 2
        assert _compute_progress(stages) == expected

    def test_skipped_stages_count_as_done(self):
        from app.core.pipeline import _compute_progress, STAGE_WEIGHT
        stages = {s: {"status": "skipped"} for s in ["upload", "parse", "chunk", "embed", "index"]}
        assert _compute_progress(stages) == 100

    def test_progress_never_exceeds_100(self):
        from app.core.pipeline import _compute_progress, STAGES
        stages = {s: {"status": "done"} for s in STAGES}
        stages["upload"]["status"] = "processing"  # double-count attempt
        assert _compute_progress(stages) <= 100


class TestGetPipelineStatus:

    async def test_returns_none_for_unknown_doc(self, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value=None)
        from app.core.pipeline import get_pipeline_status
        result = await get_pipeline_status("nonexistent", TENANT_ID)
        assert result is None

    async def test_returns_dict_with_all_stages(self, mock_conn, sample_document_row):
        mock_conn.fetchrow = AsyncMock(return_value=sample_document_row)
        mock_conn.fetch = AsyncMock(return_value=[])  # no stage rows

        from app.core.pipeline import get_pipeline_status, STAGES
        result = await get_pipeline_status(DOCUMENT_ID, TENANT_ID)

        assert result is not None
        assert result["document_id"] == DOCUMENT_ID
        assert set(result["stages"].keys()) == set(STAGES)
        assert "progress_pct" in result

    async def test_stages_from_db_override_defaults(self, mock_conn, sample_document_row):
        from datetime import datetime, timezone

        mock_conn.fetchrow = AsyncMock(return_value=sample_document_row)

        stage_row = MagicMock()
        stage_row.__getitem__ = lambda s, k: {
            "stage": "parse", "status": "done",
            "started_at": datetime.now(timezone.utc),
            "completed_at": datetime.now(timezone.utc),
            "detail": '{"parse_mode": "pymupdf"}',
        }[k]

        from unittest.mock import MagicMock
        row = MagicMock()
        row.__getitem__ = lambda s, k: {
            "stage": "parse", "status": "done",
            "started_at": datetime.now(timezone.utc),
            "completed_at": datetime.now(timezone.utc),
            "detail": '{"parse_mode": "pymupdf"}',
        }[k]

        mock_conn.fetch = AsyncMock(return_value=[row])

        from app.core.pipeline import get_pipeline_status
        result = await get_pipeline_status(DOCUMENT_ID, TENANT_ID)
        assert result["stages"]["parse"]["status"] == "done"

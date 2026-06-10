import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.worker_operations import RETRY_DELAYS, STAGES, list_dlq, retry_dlq_entry, worker_health
from app.workers.document_worker import WorkerSettings


def test_worker_limits_and_retry_schedule():
    assert WorkerSettings.max_jobs == 5
    assert WorkerSettings.job_timeout == 3600
    assert WorkerSettings.max_tries == 4
    assert RETRY_DELAYS == (60, 300, 1800)
    assert STAGES == ("queued", "started", "parsing", "chunking", "embedding", "indexing", "completed")


@pytest.mark.asyncio
async def test_worker_health_marks_stale_heartbeat_unhealthy():
    redis = AsyncMock()
    stale = datetime.now(timezone.utc) - timedelta(seconds=91)
    redis.get.side_effect = [json.dumps({"timestamp": stale.isoformat(), "active_jobs": 0}), None]
    redis.hvals.return_value = []
    redis.zcard.return_value = 3
    redis.llen.return_value = 2

    result = await worker_health(redis)

    assert result["status"] == "unhealthy"
    assert result["queue_length"] == 3
    assert result["dead_letter_queue_size"] == 2


@pytest.mark.asyncio
async def test_list_dlq_keeps_entries():
    redis = AsyncMock()
    redis.lrange.return_value = [json.dumps({"id": "entry-1", "document_id": "doc-1"})]

    entries = await list_dlq(redis)

    assert entries[0]["id"] == "entry-1"
    redis.delete.assert_not_called()
    redis.lrem.assert_not_called()


@pytest.mark.asyncio
async def test_manual_dlq_retry_removes_only_selected_entry():
    redis = AsyncMock()
    raw = json.dumps({"id": "entry-1", "document_id": "11111111-1111-1111-1111-111111111111"})
    redis.lrange.return_value = [raw]

    with patch("app.services.worker_operations.enqueue_document_job", new=AsyncMock(return_value="new-job")):
        job_id = await retry_dlq_entry(redis, "entry-1")

    assert job_id == "new-job"
    redis.lrem.assert_awaited_once_with("worker:dead_letter", 1, raw)

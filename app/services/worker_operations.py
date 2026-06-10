import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from arq.connections import ArqRedis
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Document, DocumentStatus, JobLog

log = structlog.get_logger(__name__)

DLQ_KEY = "worker:dead_letter"
HEARTBEAT_KEY = "worker:heartbeat"
ACTIVE_KEY = "worker:active"
COMPLETED_KEY = "worker:completed"
FAILED_KEY = "worker:failed"
CIRCUIT_KEY = "worker:circuit_open_until"
QUEUE_KEY = "arq:queue"
RETRY_DELAYS = (60, 300, 1800)
STAGES = ("queued", "started", "parsing", "chunking", "embedding", "indexing", "completed")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue_document_job(redis: ArqRedis, document_id: UUID | str) -> str:
    job_id = str(uuid.uuid4())
    await transition_job(job_id, document_id, "queued", attempt=0, job_type="process_document")
    await redis.enqueue_job("process_document", str(document_id), _job_id=job_id, _job_try=1)
    return job_id


async def transition_job(
    job_id: str,
    document_id: UUID | str,
    status: str,
    attempt: int,
    *,
    job_type: str = "process_document",
    stage_timing: tuple[str, int] | None = None,
    metadata: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    document_uuid = UUID(str(document_id))
    now = utcnow()
    async with SessionLocal() as db:
        document = await db.get(Document, document_uuid)
        job_log = await db.scalar(select(JobLog).where(JobLog.job_id == job_id))
        if job_log is None:
            job_log = JobLog(job_id=job_id, job_type=job_type, document_id=document_uuid, status=status, attempt=attempt, metadata_={}, stage_timings={}, attempt_history=[])
            db.add(job_log)

        job_log.status = status
        job_log.attempt = attempt
        if status == "started" and job_log.started_at is None:
            job_log.started_at = now
        if status == "started":
            job_log.error_message = None
        if status in ("completed", "failed"):
            job_log.completed_at = now
            if job_log.started_at:
                job_log.duration_ms = int((now - job_log.started_at).total_seconds() * 1000)
        if error_message:
            job_log.error_message = error_message
        if stage_timing:
            timings = dict(job_log.stage_timings or {})
            timings[stage_timing[0]] = stage_timing[1]
            job_log.stage_timings = timings
        if metadata:
            progress = dict(job_log.metadata_ or {})
            progress.update(metadata)
            job_log.metadata_ = progress
        if status in ("started", "retrying", "failed", "completed"):
            history = list(job_log.attempt_history or [])
            history.append({"attempt": attempt, "status": status, "timestamp": now.isoformat(), "error": error_message})
            job_log.attempt_history = history

        if document is not None:
            if status in STAGES or status == "failed":
                document.status = status
            if status in STAGES:
                document.processing_stage = status
            if status == "failed":
                document.processing_stage = "failed"
                document.error_message = error_message
            elif status == "started":
                document.error_message = None
        await db.commit()


async def mark_active(redis: ArqRedis, job_id: str, document_id: str, attempt: int) -> None:
    payload = json.dumps({"job_id": job_id, "document_id": document_id, "attempt": attempt, "started_at": utcnow().isoformat()})
    await redis.hset(ACTIVE_KEY, job_id, payload)


async def clear_active(redis: ArqRedis, job_id: str) -> None:
    await redis.hdel(ACTIVE_KEY, job_id)


async def record_outcome(redis: ArqRedis, success: bool) -> None:
    key = COMPLETED_KEY if success else FAILED_KEY
    now = time.time()
    member = f"{now}:{uuid.uuid4()}"
    await redis.zadd(key, {member: now})
    await redis.zremrangebyscore(key, 0, now - 86400)
    if not success:
        failures = await redis.zcount(FAILED_KEY, now - 3600, now)
        if failures > 10:
            open_until = int(now + 900)
            await redis.set(CIRCUIT_KEY, str(open_until))
            log.critical("worker_circuit_breaker_open", failures_last_hour=failures, open_until=open_until)


async def circuit_status(redis: ArqRedis) -> dict:
    raw = await redis.get(CIRCUIT_KEY)
    open_until = int(raw or 0)
    now = int(time.time())
    return {"open": open_until > now, "open_until": datetime.fromtimestamp(open_until, timezone.utc).isoformat() if open_until else None, "retry_after_seconds": max(0, open_until - now)}


async def move_to_dlq(redis: ArqRedis, job_id: str, document_id: str, attempts: int, error: str) -> dict:
    entry = {"id": str(uuid.uuid4()), "job_id": job_id, "job_type": "process_document", "payload": {"document_id": document_id}, "attempts": attempts, "error": error, "document_id": document_id, "moved_at": utcnow().isoformat()}
    await redis.rpush(DLQ_KEY, json.dumps(entry))
    return entry


async def list_dlq(redis: ArqRedis) -> list[dict]:
    values = await redis.lrange(DLQ_KEY, 0, -1)
    return [json.loads(value) for value in values]


async def retry_dlq_entry(redis: ArqRedis, entry_id: str) -> str | None:
    for raw in await redis.lrange(DLQ_KEY, 0, -1):
        entry = json.loads(raw)
        if entry["id"] == entry_id:
            new_job_id = await enqueue_document_job(redis, entry["document_id"])
            await redis.lrem(DLQ_KEY, 1, raw)
            return new_job_id
    return None


async def retry_all_dlq(redis: ArqRedis) -> int:
    entries = await list_dlq(redis)
    for entry in entries:
        await enqueue_document_job(redis, entry["document_id"])
    if entries:
        await redis.delete(DLQ_KEY)
    return len(entries)


async def heartbeat_loop(redis: ArqRedis) -> None:
    while True:
        try:
            now = time.time()
            active = await redis.hlen(ACTIVE_KEY)
            completed = await redis.zcount(COMPLETED_KEY, now - 3600, now)
            failed = await redis.zcount(FAILED_KEY, now - 3600, now)
            heartbeat = {"timestamp": utcnow().isoformat(), "active_jobs": active, "completed_last_hour": completed, "failed_last_hour": failed}
            await redis.set(HEARTBEAT_KEY, json.dumps(heartbeat), ex=120)
        except Exception as exc:
            log.error("worker_heartbeat_failed", error=str(exc))
        await asyncio.sleep(30)


async def worker_health(redis: ArqRedis) -> dict:
    raw = await redis.get(HEARTBEAT_KEY)
    heartbeat = json.loads(raw) if raw else {}
    timestamp = datetime.fromisoformat(heartbeat["timestamp"]) if heartbeat.get("timestamp") else None
    healthy = timestamp is not None and (utcnow() - timestamp).total_seconds() <= 90
    active = [json.loads(value) for value in await redis.hvals(ACTIVE_KEY)]
    return {
        "status": "healthy" if healthy else "unhealthy",
        "last_heartbeat": heartbeat.get("timestamp"),
        "queue_length": await redis.zcard(QUEUE_KEY),
        "active_jobs": active,
        "active_job_count": len(active),
        "dead_letter_queue_size": await redis.llen(DLQ_KEY),
        "completed_last_hour": heartbeat.get("completed_last_hour", 0),
        "failed_last_hour": heartbeat.get("failed_last_hour", 0),
        "circuit_breaker": await circuit_status(redis),
    }


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

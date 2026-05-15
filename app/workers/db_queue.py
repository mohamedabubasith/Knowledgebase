"""
PostgreSQL-backed durable job queue.

- enqueue(): insert pending job — returns None (silent skip) if document already deleted
- claim():   SELECT FOR UPDATE SKIP LOCKED — safe for concurrent workers
- ack():     mark done
- nack():    retry with exponential backoff (20s → 40s → 80s), or mark failed
- recover_stale_jobs(): reset stuck 'processing' jobs on startup
- cleanup_old_jobs():   delete done/failed rows older than N days (prevents table bloat)

Workers use adaptive-backoff polling (0.5s → max 5s) to reduce idle DB pressure.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import PipelineJob
from app.db.session import get_session_factory

log = structlog.get_logger(__name__)

LOCK_TIMEOUT_MINUTES  = 5     # reclaim jobs locked longer than this on startup
_POLL_MIN_S           = 0.5   # first sleep after empty poll
_POLL_MAX_S           = 5.0   # cap on adaptive backoff sleep
_POLL_FACTOR          = 1.5   # growth factor per empty poll
CLEANUP_RETAIN_DAYS   = 7     # keep done/failed jobs this many days


async def enqueue(
    stage: str,
    document_id: str,
    tenant_id: str,
    payload: dict,
    max_attempts: int = 3,
) -> Optional[str]:
    """
    Insert a new pending job. Returns the job id.
    Returns None (silently) if the document was already deleted (FK violation) —
    this happens when a worker finishes a stage just as the user deletes the doc.
    """
    factory = get_session_factory()
    async with factory() as session:
        job = PipelineJob(
            document_id=document_id,
            tenant_id=tenant_id,
            stage=stage,
            status="pending",
            payload=payload,
            max_attempts=max_attempts,
        )
        session.add(job)
        try:
            await session.commit()
        except IntegrityError:
            # document_id FK violated — document was deleted while pipeline was running
            await session.rollback()
            log.info("enqueue_skipped_doc_deleted", stage=stage, document_id=document_id)
            return None
        await session.refresh(job)
        log.debug("job_enqueued", stage=stage, document_id=document_id, job_id=job.id)
        return job.id


async def claim(stage: str) -> Optional[PipelineJob]:
    """
    Claim the next available pending job for *stage*.
    Uses SELECT FOR UPDATE SKIP LOCKED — safe with N concurrent workers.
    Returns None when nothing is ready.
    """
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            row = (await session.execute(
                select(PipelineJob)
                .where(
                    PipelineJob.stage == stage,
                    PipelineJob.status == "pending",
                    PipelineJob.scheduled_at <= now,
                )
                .order_by(PipelineJob.scheduled_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()

            if row is None:
                return None

            row.status = "processing"
            row.locked_at = now
            row.attempt += 1
            await session.flush()
            # Detach before session closes so caller owns the object
            session.expunge(row)
            return row


async def ack(job_id: str) -> None:
    """
    Mark job as successfully completed.
    Safe to call even if the row was already cascade-deleted (UPDATE 0 rows = no-op).
    """
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(PipelineJob)
            .where(PipelineJob.id == job_id)
            .values(status="done", locked_at=None)
        )
        await session.commit()


async def nack(job_id: str, error: str) -> None:
    """
    Record failure for this attempt.
    If attempts < max_attempts: reschedule with exponential backoff (2^attempt * 10s).
    If exhausted: mark permanently failed.
    Safe to call if job row was cascade-deleted — SELECT returns None → no-op.
    """
    factory = get_session_factory()
    async with factory() as session:
        row = (await session.execute(
            select(PipelineJob).where(PipelineJob.id == job_id)
        )).scalar_one_or_none()
        if row is None:
            # Job was cascade-deleted (document purged mid-pipeline) — nothing to do
            return

        if row.attempt >= row.max_attempts:
            await session.execute(
                update(PipelineJob)
                .where(PipelineJob.id == job_id)
                .values(status="failed", last_error=error[:2000], locked_at=None)
            )
            log.warning("job_permanently_failed", job_id=job_id, stage=row.stage,
                        document_id=row.document_id, attempts=row.attempt)
        else:
            delay_s = (2 ** row.attempt) * 10  # 20s, 40s, 80s
            scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay_s)
            await session.execute(
                update(PipelineJob)
                .where(PipelineJob.id == job_id)
                .values(
                    status="pending",
                    last_error=error[:2000],
                    locked_at=None,
                    scheduled_at=scheduled_at,
                )
            )
            log.info("job_rescheduled", job_id=job_id, stage=row.stage,
                     attempt=row.attempt, delay_s=delay_s)
        await session.commit()


async def recover_stale_jobs() -> int:
    """
    Reset 'processing' jobs locked longer than LOCK_TIMEOUT_MINUTES back to 'pending'.
    Call once at startup to recover jobs lost during a crash/restart.
    Returns count of recovered jobs.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOCK_TIMEOUT_MINUTES)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            update(PipelineJob)
            .where(
                PipelineJob.status == "processing",
                PipelineJob.locked_at <= cutoff,
            )
            .values(status="pending", locked_at=None)
        )
        await session.commit()
        count = result.rowcount or 0
        if count:
            log.warning("stale_jobs_recovered", count=count)
        return count


async def cleanup_old_jobs(retain_days: int = CLEANUP_RETAIN_DAYS) -> int:
    """
    Delete done/failed pipeline_jobs older than *retain_days*.
    Prevents table bloat for high-volume deployments (100k+ customers).
    Call once at startup; schedule periodically if needed.
    Returns count deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            delete(PipelineJob).where(
                PipelineJob.status.in_(["done", "failed"]),
                PipelineJob.created_at <= cutoff,
            )
        )
        await session.commit()
        count = result.rowcount or 0
        if count:
            log.info("old_jobs_cleaned", count=count, retain_days=retain_days)
        return count


async def wait_for_job(stage: str) -> PipelineJob:
    """
    Block until a job is available for *stage*.
    Uses adaptive backoff: starts at _POLL_MIN_S, grows by _POLL_FACTOR each
    empty poll, capped at _POLL_MAX_S. Resets to min when a job is found.
    Keeps idle DB load low on low-resource deployments.
    """
    sleep_s = _POLL_MIN_S
    while True:
        job = await claim(stage)
        if job is not None:
            return job   # sleep_s implicitly resets on next call
        await asyncio.sleep(sleep_s)
        sleep_s = min(sleep_s * _POLL_FACTOR, _POLL_MAX_S)

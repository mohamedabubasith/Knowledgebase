"""
Index worker: force-update fts_vector for all chunks → mark document indexed.
Uses PostgreSQL-backed job queue with retry + exponential backoff.
"""
import asyncio
import structlog
from sqlalchemy import update
from sqlalchemy.sql import func

from app.core.pipeline import update_stage
from app.db.models import Chunk, Document
from app.db.session import get_session_factory
from app.workers.db_queue import ack, nack, wait_for_job

log = structlog.get_logger(__name__)


async def _process_index_job(job_id: str, payload: dict) -> None:
    document_id: str = payload["document_id"]
    tenant_id: str   = payload["tenant_id"]

    try:
        await update_stage(document_id, tenant_id, "index", "processing")

        factory = get_session_factory()
        async with factory() as session:
            # Force-update fts_vector for ALL chunks of this document.
            # The DB trigger handles new inserts, but we explicitly update here
            # to guarantee fts_vector is always populated (covers edge cases
            # where trigger didn't fire, or chunks were inserted via bulk path).
            result = await session.execute(
                update(Chunk)
                .where(Chunk.document_id == document_id, Chunk.tenant_id == tenant_id)
                .values(fts_vector=func.to_tsvector("english", Chunk.chunk_text))
            )
            updated = result.rowcount or 0
            await session.execute(
                update(Document).where(Document.id == document_id).values(status="indexed")
            )
            await session.commit()

        await update_stage(document_id, tenant_id, "index", "done", {"fts_updated": updated})
        log.info("index_done", document_id=document_id)
        await ack(job_id)

    except Exception as e:
        log.exception("index_error", document_id=document_id)
        await update_stage(document_id, tenant_id, "index", "failed", {"error": str(e)})
        await nack(job_id, str(e))


async def run_index_worker() -> None:
    log.info("index_worker_started")
    while True:
        try:
            job = await wait_for_job("index")
            await _process_index_job(job.id, job.payload)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception("index_worker_unexpected", error=str(e))

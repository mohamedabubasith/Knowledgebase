import asyncio
import structlog
from sqlalchemy import update
from sqlalchemy.sql import func

from app.core.pipeline import update_stage
from app.db.models import Chunk, Document
from app.db.session import get_session_factory
from app.workers.queue import index_queue

log = structlog.get_logger(__name__)


async def _process_index_job(job: dict) -> None:
    document_id: str = job["document_id"]
    tenant_id: str = job["tenant_id"]

    try:
        await update_stage(document_id, tenant_id, "index", "processing")

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                update(Chunk)
                .where(Chunk.document_id == document_id, Chunk.fts_vector.is_(None))
                .values(fts_vector=func.to_tsvector("english", Chunk.chunk_text))
            )
            updated = result.rowcount or 0
            await session.execute(
                update(Document).where(Document.id == document_id).values(status="indexed")
            )
            await session.commit()

        await update_stage(document_id, tenant_id, "index", "done", {"fts_updated": updated})
        log.info("index_done", document_id=document_id)

    except Exception as e:
        log.exception("index_error", document_id=document_id)
        await update_stage(document_id, tenant_id, "index", "failed", {"error": str(e)})


async def run_index_worker() -> None:
    log.info("index_worker_started")
    while True:
        try:
            job = await index_queue.get()
            await _process_index_job(job)
            index_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception("index_worker_unexpected", error=str(e))

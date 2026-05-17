"""
Purge worker: delete document from MinIO + vector store + Postgres.
Order: vector store first (idempotent), then MinIO, then Postgres.
Uses PostgreSQL-backed job queue with retry + exponential backoff.
"""
import asyncio
import structlog
from sqlalchemy import delete, update

from app.db.models import AuditLog, Document
from app.db.session import get_session_factory
from app.storage.minio_client import delete_file
from app.storage import mindsdb_client as mdb
from app.vectorstore import get_vector_store
from app.workers.db_queue import ack, nack, wait_for_job

log = structlog.get_logger(__name__)


async def _process_purge_job(job_id: str, payload: dict) -> None:
    document_id: str = payload["document_id"]
    tenant_id: str   = payload["tenant_id"]
    minio_path: str  = payload["minio_path"]
    factory = get_session_factory()

    try:
        # 1. Vector store (idempotent)
        try:
            await get_vector_store().delete_by_document(document_id, tenant_id)
        except Exception as e:
            log.warning("purge_vector_fail", document_id=document_id, error=str(e))

        # 2. MindsDB file (tabular docs only — safe to call for all, returns True if 404)
        try:
            import asyncio as _asyncio
            mdb_name = mdb.mindsdb_name(document_id)
            loop = _asyncio.get_event_loop()
            await loop.run_in_executor(None, mdb.delete_file, mdb_name)
        except Exception as e:
            log.warning("purge_mindsdb_fail", document_id=document_id, error=str(e))

        # 3. MinIO
        try:
            await delete_file(minio_path)
        except Exception as e:
            log.warning("purge_minio_fail", document_id=document_id, error=str(e))

        # 3. Postgres (cascade deletes chunks + pipeline_stages + pipeline_jobs)
        async with factory() as session:
            await session.execute(
                delete(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
            )
            session.add(AuditLog(
                tenant_id=tenant_id,
                action="delete",
                resource_type="document",
                resource_id=document_id,
            ))
            await session.commit()

        log.info("purge_done", document_id=document_id)
        # Note: ack not called — job row was cascade-deleted with the document above.
        # That's fine; the job is gone and won't be re-claimed.

    except Exception as e:
        log.exception("purge_error", document_id=document_id, error=str(e))
        try:
            async with factory() as session:
                await session.execute(
                    update(Document).where(Document.id == document_id).values(status="error")
                )
                await session.commit()
        except Exception:
            pass
        await nack(job_id, str(e))


async def run_purge_worker() -> None:
    log.info("purge_worker_started")
    while True:
        try:
            job = await wait_for_job("purge")
            await _process_purge_job(job.id, job.payload)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception("purge_worker_unexpected", error=str(e))

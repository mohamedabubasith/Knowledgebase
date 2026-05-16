"""
Ingest worker: fetch file from MinIO → parse → chunk → persist → enqueue embed.
Writes stage updates via pipeline tracker (Postgres + SSE broadcast).
Uses PostgreSQL-backed job queue with retry + exponential backoff.

Tabular branch (CSV / XLSX / TSV)
----------------------------------
Tabular files skip the normal parse → chunk pipeline.  Instead:
  1. Profile schema with DuckDB (column names, types, sample values, row count)
  2. Persist a single "summary" Chunk that describes the table — this is what
     gets embedded and indexed for hybrid search
  3. Mark Document.is_tabular = True and store table_schema as JSONB
  4. Enqueue embed as usual (summary chunk will be embedded)
"""
import asyncio
import structlog
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.pipeline import update_stage
from app.db.models import Chunk, Document
from app.db.session import get_session_factory
from app.ingestion.chunker import chunk_document
from app.ingestion.tabular_profiler import (
    build_summary_chunk,
    is_tabular as _is_tabular_file,
    profile_tabular,
)
from app.parsers.router import parse_document
from app.storage.minio_client import download_file
from app.workers.db_queue import ack, enqueue, nack, wait_for_job

log = structlog.get_logger(__name__)


async def _set_doc_status(document_id: str, status: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Document).where(Document.id == document_id).values(status=status)
        )
        await session.commit()


async def _process_tabular_job(
    job_id: str,
    document_id: str,
    tenant_id: str,
    filename: str,
    mime_type: str,
    minio_path: str,
) -> None:
    """Tabular fast-path: profile → summary chunk → embed."""
    try:
        await update_stage(document_id, tenant_id, "parse", "processing")
        await _set_doc_status(document_id, "parsing")

        data = await download_file(minio_path)

        # Profile schema
        schema = await profile_tabular(filename, data, mime_type)

        await update_stage(document_id, tenant_id, "parse", "done", {
            "parse_mode":  "tabular",
            "row_count":   schema["row_count"],
            "col_count":   len(schema["columns"]),
            "sheet_name":  schema.get("sheet_name"),
        })

        # Build summary chunk text for embedding
        await update_stage(document_id, tenant_id, "chunk", "processing")

        summary_text = build_summary_chunk(filename, schema)

        # Persist: mark document as tabular + store schema + insert summary chunk
        import hashlib as _hl
        chunk_checksum = _hl.sha256(summary_text.encode()).hexdigest()

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                pg_insert(Chunk).on_conflict_do_nothing(
                    index_elements=["document_id", "chunk_index"]
                ),
                [{
                    "document_id": document_id,
                    "tenant_id":   tenant_id,
                    "chunk_index": 0,
                    "chunk_text":  summary_text,
                    "token_count": len(summary_text.split()),  # approx — embedder handles actual
                    "page_number": None,
                    "start_char":  0,
                    "end_char":    len(summary_text),
                    "checksum":    chunk_checksum,
                }],
            )
            await session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status="chunked",
                    parse_mode="tabular",
                    is_tabular=True,
                    table_schema=schema,
                )
            )
            await session.commit()

        await update_stage(document_id, tenant_id, "chunk", "done", {
            "chunk_count": 1,
            "row_count":   schema["row_count"],
        })

        log.info("tabular_ingest_done", document_id=document_id, rows=schema["row_count"])

        await enqueue("embed", document_id, tenant_id, {"document_id": document_id, "tenant_id": tenant_id})
        await ack(job_id)

    except Exception as e:
        log.exception("tabular_ingest_error", document_id=document_id)
        await update_stage(document_id, tenant_id, "parse", "failed", {"error": str(e)})
        await _set_doc_status(document_id, "error")
        await nack(job_id, str(e))


async def _process_ingest_job(job_id: str, payload: dict) -> None:
    document_id: str = payload["document_id"]
    tenant_id: str   = payload["tenant_id"]
    filename: str    = payload["filename"]
    mime_type: str   = payload["mime_type"]
    minio_path: str  = payload["minio_path"]

    # ── Tabular fast-path ────────────────────────────────────────────────────
    if _is_tabular_file(filename, mime_type):
        log.info("tabular_doc_detected", document_id=document_id, filename=filename)
        await _process_tabular_job(job_id, document_id, tenant_id, filename, mime_type, minio_path)
        return

    try:
        # ── Stage: parse ─────────────────────────────────────────────────────
        await update_stage(document_id, tenant_id, "parse", "processing")
        await _set_doc_status(document_id, "parsing")

        data   = await download_file(minio_path)
        parsed = await parse_document(filename, data, mime_type)

        if not parsed.raw_text.strip():
            await update_stage(document_id, tenant_id, "parse", "failed",
                               {"error": "Empty text after parsing", "parse_mode": parsed.parse_mode})
            await _set_doc_status(document_id, "parse_failed")
            await ack(job_id)   # not retryable — empty doc
            return

        await update_stage(document_id, tenant_id, "parse", "done", {
            "parse_mode": parsed.parse_mode,
            "char_count": parsed.char_count,
            "page_count": len(parsed.pages),
        })

        # ── Stage: chunk ─────────────────────────────────────────────────────
        await update_stage(document_id, tenant_id, "chunk", "processing")

        chunks = chunk_document(parsed)
        if not chunks:
            await update_stage(document_id, tenant_id, "chunk", "failed",
                               {"error": "No chunks produced"})
            await _set_doc_status(document_id, "chunk_failed")
            await ack(job_id)   # not retryable — document produced no content
            return

        chunk_rows = [
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "chunk_index": c.chunk_index,
                "chunk_text": c.text,
                "token_count": c.token_count,
                "page_number": c.page_number,
                "start_char": c.start_char,
                "end_char": c.end_char,
                "checksum": c.checksum,
            }
            for c in chunks
        ]

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                pg_insert(Chunk).on_conflict_do_nothing(
                    index_elements=["document_id", "chunk_index"]
                ),
                chunk_rows,
            )
            await session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status="chunked",
                    page_count=len(parsed.pages) or None,
                    parse_mode=parsed.parse_mode,
                )
            )
            await session.commit()

        await update_stage(document_id, tenant_id, "chunk", "done", {
            "chunk_count": len(chunks),
            "avg_tokens": sum(c.token_count for c in chunks) // len(chunks),
        })

        log.info("ingest_done", document_id=document_id, chunks=len(chunks))

        # Enqueue next stage then ack this job
        await enqueue("embed", document_id, tenant_id, {"document_id": document_id, "tenant_id": tenant_id})
        await ack(job_id)

    except Exception as e:
        log.exception("ingest_error", document_id=document_id)
        await update_stage(document_id, tenant_id, "parse", "failed", {"error": str(e)})
        await _set_doc_status(document_id, "error")
        await nack(job_id, str(e))


async def run_ingest_worker() -> None:
    log.info("ingest_worker_started")
    while True:
        try:
            job = await wait_for_job("ingest")
            await _process_ingest_job(job.id, job.payload)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception("ingest_worker_unexpected", error=str(e))

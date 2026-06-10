import asyncio
import time
from contextlib import suppress
from uuid import UUID

from arq import Retry, func
from arq.connections import RedisSettings
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.embedding import get_embeddings_batch, get_sparse_embedding
from app.core.minio import download_file
from app.core.qdrant import ChunkVector, delete_chunks_by_document, upsert_chunks
from app.models import Chunk, Document, KnowledgeBase
from app.services.document_processor import chunk_text, parse_document_bytes
from app.services.worker_operations import (
    RETRY_DELAYS,
    circuit_status,
    clear_active,
    format_exception,
    heartbeat_loop,
    mark_active,
    move_to_dlq,
    record_outcome,
    transition_job,
)


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def process_document(ctx, document_id: str):
    redis = ctx["redis"]
    job_id = ctx["job_id"]
    attempt = int(ctx.get("job_try", 1))
    circuit = await circuit_status(redis)
    if circuit["open"]:
        await transition_job(job_id, document_id, "retrying", attempt, error_message="Worker circuit breaker is open")
        raise Retry(defer=circuit["retry_after_seconds"])

    await mark_active(redis, job_id, document_id, attempt)
    await transition_job(job_id, document_id, "started", attempt)
    stage_started = time.perf_counter()

    try:
        await transition_job(job_id, document_id, "parsing", attempt, stage_timing=("started", elapsed_ms(stage_started)))
        stage_started = time.perf_counter()
        async with SessionLocal() as db:
            document = await db.get(Document, UUID(document_id))
            if not document:
                return
            document_info = {
                "file_size": document.file_size,
                "file_type": document.file_type,
                "document_name": document.original_filename,
                "embedding_model": settings.embed_model,
            }
            data = await download_file(document.file_path)
            text = await asyncio.to_thread(parse_document_bytes, data, document.original_filename)

            await transition_job(job_id, document_id, "chunking", attempt, stage_timing=("parsing", elapsed_ms(stage_started)), metadata=document_info)
            stage_started = time.perf_counter()
            parts = chunk_text(text)

            await transition_job(job_id, document_id, "embedding", attempt, stage_timing=("chunking", elapsed_ms(stage_started)), metadata={"chunks_created": len(parts)})
            stage_started = time.perf_counter()
            vectors = await asyncio.to_thread(get_embeddings_batch, parts, settings.embed_batch_size)

            await transition_job(job_id, document_id, "indexing", attempt, stage_timing=("embedding", elapsed_ms(stage_started)))
            stage_started = time.perf_counter()
            await delete_chunks_by_document(str(document.knowledge_base_id), str(document.id))
            await db.execute(delete(Chunk).where(Chunk.document_id == document.id))
            chunks = [
                Chunk(document_id=document.id, knowledge_base_id=document.knowledge_base_id, content=part, chunk_index=index, metadata_={"filename": document.original_filename})
                for index, part in enumerate(parts)
            ]
            db.add_all(chunks)
            await db.flush()
            for chunk in chunks:
                chunk.qdrant_point_id = str(chunk.id)
            kb = await db.get(KnowledgeBase, document.knowledge_base_id)
            await upsert_chunks(
                str(document.knowledge_base_id),
                [
                    ChunkVector(
                        id=str(chunk.id),
                        dense=vector,
                        sparse=get_sparse_embedding(chunk.content),
                        payload={
                            "document_id": str(document.id),
                            "kb_id": str(document.knowledge_base_id),
                            "kb_name": kb.name if kb else "",
                            "chunk_index": chunk.chunk_index,
                            "document_name": document.original_filename,
                            "object_key": document.file_path,
                            "content": chunk.content,
                            "metadata": chunk.metadata_,
                        },
                    )
                    for chunk, vector in zip(chunks, vectors)
                ],
            )
            document.chunk_count = len(parts)
            await db.commit()

        await transition_job(job_id, document_id, "completed", attempt, stage_timing=("indexing", elapsed_ms(stage_started)))
        await record_outcome(redis, success=True)
    except (Exception, asyncio.CancelledError) as exc:
        error = format_exception(exc)
        await record_outcome(redis, success=False)
        if attempt <= len(RETRY_DELAYS):
            await transition_job(job_id, document_id, "retrying", attempt, error_message=error)
            raise Retry(defer=RETRY_DELAYS[attempt - 1]) from exc
        await transition_job(job_id, document_id, "failed", attempt, error_message=error)
        await move_to_dlq(redis, job_id, document_id, attempt, error)
    finally:
        await clear_active(redis, job_id)


async def startup(ctx):
    ctx["heartbeat_task"] = asyncio.create_task(heartbeat_loop(ctx["redis"]))


async def shutdown(ctx):
    task = ctx.get("heartbeat_task")
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class WorkerSettings:
    functions = [func(process_document, max_tries=4, timeout=3600)]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5
    job_timeout = 3600
    max_tries = 4
    on_startup = startup
    on_shutdown = shutdown

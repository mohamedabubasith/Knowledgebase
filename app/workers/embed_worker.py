import asyncio
import structlog
from sqlalchemy import select, update

from app.core.pipeline import update_stage
from app.db.models import Chunk, Document
from app.db.session import get_session_factory
from app.embedding.embedder import embed_batch
from app.vectorstore import get_vector_store
from app.vectorstore.backend import VectorPoint
from app.workers.queue import embed_queue, index_queue

log = structlog.get_logger(__name__)


async def _set_doc_status(document_id: str, status: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Document).where(Document.id == document_id).values(status=status)
        )
        await session.commit()


async def _process_embed_job(job: dict) -> None:
    document_id: str = job["document_id"]
    tenant_id: str = job["tenant_id"]

    try:
        await update_stage(document_id, tenant_id, "embed", "processing")
        await _set_doc_status(document_id, "embedding")

        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(
                select(Chunk)
                .where(Chunk.document_id == document_id, Chunk.tenant_id == tenant_id)
                .order_by(Chunk.chunk_index)
            )).scalars().all()

        if not rows:
            await update_stage(document_id, tenant_id, "embed", "failed", {"error": "No chunks found"})
            await _set_doc_status(document_id, "embed_failed")
            return

        texts = [r.chunk_text for r in rows]
        vectors = await embed_batch(texts)

        if len(vectors) != len(rows):
            raise ValueError(f"Embed count mismatch: {len(vectors)} vs {len(rows)}")

        points = [
            VectorPoint(
                point_id=str(r.id),
                vector=vectors[i],
                payload={
                    "chunk_id": str(r.id),
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "chunk_index": r.chunk_index,
                    "page_number": r.page_number,
                    "start_char": r.start_char,
                    "end_char": r.end_char,
                    "checksum": r.checksum,
                    "text_preview": r.chunk_text[:256],
                },
            )
            for i, r in enumerate(rows)
        ]

        try:
            await get_vector_store().upsert_batch(points)
        except Exception as upsert_err:
            # Qdrant dimension mismatch — recreate collection with correct dim and retry once
            err_str = str(upsert_err)
            if "Vector dimension error" in err_str or "expected dim" in err_str:
                log.warning("embed_dim_mismatch_recreating_collection", error=err_str)
                from app.core.registry import registry
                from qdrant_client import AsyncQdrantClient
                from qdrant_client.models import Distance, VectorParams
                from urllib.parse import urlparse, urlunparse
                from app.core.config import settings

                def _with_port(url: str) -> str:
                    p = urlparse(url)
                    if not p.port:
                        port = 443 if p.scheme == "https" else 80
                        return urlunparse((p.scheme, f"{p.hostname}:{port}", p.path, p.params, p.query, p.fragment))
                    return url

                client = AsyncQdrantClient(
                    url=_with_port(settings.qdrant_url),
                    api_key=settings.qdrant_api_key or None,
                    timeout=15.0,
                    prefer_grpc=False,
                )
                await client.delete_collection(settings.qdrant_collection)
                await client.create_collection(
                    collection_name=settings.qdrant_collection,
                    vectors_config=VectorParams(size=registry.embed_dimension, distance=Distance.COSINE),
                    on_disk_payload=True,
                )
                await client.close()
                log.info("collection_recreated_retrying", dim=registry.embed_dimension)
                await get_vector_store().upsert_batch(points)
            else:
                raise

        async with factory() as session:
            # Bulk update: set vector_id = id for all embedded chunks
            await session.execute(
                update(Chunk),
                [{"id": str(r.id), "vector_id": str(r.id)} for r in rows],
            )
            await session.execute(
                update(Document).where(Document.id == document_id).values(status="embedded")
            )
            await session.commit()

        await update_stage(document_id, tenant_id, "embed", "done", {
            "vector_count": len(points),
            "backend": "qdrant" if hasattr(get_vector_store(), "_client") else "chroma",
        })

        log.info("embed_done", document_id=document_id, count=len(points))
        await index_queue.put({"document_id": document_id, "tenant_id": tenant_id})

    except Exception as e:
        log.exception("embed_error", document_id=document_id)
        await update_stage(document_id, tenant_id, "embed", "failed", {"error": str(e)})
        await _set_doc_status(document_id, "embed_failed")


async def run_embed_worker() -> None:
    log.info("embed_worker_started")
    while True:
        try:
            job = await embed_queue.get()
            await _process_embed_job(job)
            embed_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception("embed_worker_unexpected", error=str(e))

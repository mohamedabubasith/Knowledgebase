"""
ChromaDB embedded fallback — runs in-process, no server required.
Uses PersistentClient so data survives restarts.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import structlog

from app.core.config import settings
from app.vectorstore.backend import VectorHit, VectorPoint, VectorStoreBackend

log = structlog.get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chroma")
_BATCH_SIZE = 512


class ChromaStore(VectorStoreBackend):

    def __init__(self) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=settings.qdrant_collection,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("chroma_store_ready", path=settings.chroma_persist_dir)

    @staticmethod
    def _sanitize(payload: dict) -> dict:
        """ChromaDB only accepts str/int/float/bool metadata values."""
        return {k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool))}

    def _sync_upsert(self, points: list[VectorPoint]) -> None:
        for i in range(0, len(points), _BATCH_SIZE):
            batch = points[i : i + _BATCH_SIZE]
            self._collection.upsert(
                ids=[p.point_id for p in batch],
                embeddings=[p.vector for p in batch],
                metadatas=[self._sanitize(p.payload) for p in batch],
            )

    def _sync_search(
        self, vector: list[float], tenant_id: str, top_k: int, document_id: Optional[str]
    ) -> list[VectorHit]:
        # ChromaDB $and requires {"$and": [{"field": {"$eq": val}}, ...]}
        if document_id:
            where: dict = {"$and": [
                {"tenant_id": {"$eq": tenant_id}},
                {"document_id": {"$eq": document_id}},
            ]}
        else:
            where = {"tenant_id": {"$eq": tenant_id}}

        results = self._collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            where=where,
            include=["metadatas", "distances"],
        )

        hits = []
        ids = results["ids"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]
        for pid, dist, meta in zip(ids, distances, metadatas):
            # ChromaDB cosine distance → similarity: score = 1 - distance
            hits.append(VectorHit(point_id=pid, score=1.0 - dist, payload=meta or {}))
        return hits

    def _sync_delete(self, document_id: str, tenant_id: str) -> None:
        self._collection.delete(where={"$and": [
            {"document_id": {"$eq": document_id}},
            {"tenant_id": {"$eq": tenant_id}},
        ]})

    async def upsert_batch(self, points: list[VectorPoint]) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_executor, self._sync_upsert, points)
        log.debug("chroma_upsert_ok", count=len(points))

    async def search(
        self,
        vector: list[float],
        tenant_id: str,
        top_k: int,
        document_id: Optional[str] = None,
    ) -> list[VectorHit]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor, self._sync_search, vector, tenant_id, top_k, document_id
        )

    async def delete_by_document(self, document_id: str, tenant_id: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_executor, self._sync_delete, document_id, tenant_id)

    async def health_check(self) -> bool:
        try:
            self._collection.count()
            return True
        except Exception:
            return False

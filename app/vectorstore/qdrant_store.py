from typing import Optional

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    FilterSelector,
)

from urllib.parse import urlparse, urlunparse

from app.core.config import settings
from app.vectorstore.backend import VectorHit, VectorPoint, VectorStoreBackend

log = structlog.get_logger(__name__)

_BATCH_SIZE = 256


def _with_port(url: str) -> str:
    p = urlparse(url)
    if not p.port:
        port = 443 if p.scheme == "https" else 80
        netloc = f"{p.hostname}:{port}"
        return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
    return url


class QdrantStore(VectorStoreBackend):

    def __init__(self) -> None:
        self._client = AsyncQdrantClient(
            url=_with_port(settings.qdrant_url),
            api_key=settings.qdrant_api_key or None,
            timeout=30.0,
            prefer_grpc=False,
        )

    async def upsert_batch(self, points: list[VectorPoint]) -> None:
        structs = [
            PointStruct(id=p.point_id, vector=p.vector, payload=p.payload)
            for p in points
        ]
        for i in range(0, len(structs), _BATCH_SIZE):
            batch = structs[i : i + _BATCH_SIZE]
            await self._client.upsert(
                collection_name=settings.qdrant_collection,
                points=batch,
                wait=True,
            )
        log.debug("qdrant_upsert_ok", count=len(points))

    async def search(
        self,
        vector: list[float],
        tenant_id: str,
        top_k: int,
        document_id: Optional[str] = None,
    ) -> list[VectorHit]:
        must = [FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]
        if document_id:
            must.append(FieldCondition(key="document_id", match=MatchValue(value=document_id)))

        results = await self._client.search(
            collection_name=settings.qdrant_collection,
            query_vector=vector,
            query_filter=Filter(must=must),
            limit=top_k,
            with_payload=True,
        )
        return [
            VectorHit(point_id=str(r.id), score=float(r.score), payload=r.payload or {})
            for r in results
        ]

    async def delete_by_document(self, document_id: str, tenant_id: str) -> None:
        await self._client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    ]
                )
            ),
        )
        log.info("qdrant_delete_ok", document_id=document_id)

    async def health_check(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False

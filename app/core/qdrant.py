from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import structlog
from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings

log = structlog.get_logger(__name__)
_client: AsyncQdrantClient | None = None
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"
_BATCH_SIZE = 256


@dataclass
class ChunkVector:
    id: str
    dense: list[float]
    sparse: dict[int, float]
    payload: dict[str, Any]


def collection_name(kb_id: str) -> str:
    return f"kb_{kb_id}"


def _with_port(url: str) -> str:
    parsed = urlparse(url)
    if parsed.port:
        return url
    port = 443 if parsed.scheme == "https" else 80
    return urlunparse(parsed._replace(netloc=f"{parsed.hostname}:{port}"))


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            url=_with_port(settings.qdrant_url),
            api_key=settings.qdrant_api_key or None,
            prefer_grpc=settings.qdrant_prefer_grpc,
            timeout=30.0,
        )
    return _client


async def init_qdrant() -> None:
    collections = await get_client().get_collections()
    log.info("qdrant_ready", collections=len(collections.collections))


async def create_collection(kb_id: str) -> None:
    name = collection_name(kb_id)
    if await get_client().collection_exists(name):
        info = await get_client().get_collection(name)
        vectors = info.config.params.vectors
        existing_dimension = vectors[DENSE_VECTOR].size if isinstance(vectors, dict) else vectors.size
        if existing_dimension == settings.embed_dimension:
            return
        log.warning(
            "qdrant_collection_dimension_changed",
            collection=name,
            existing_dimension=existing_dimension,
            required_dimension=settings.embed_dimension,
        )
        await get_client().delete_collection(name)
    await get_client().create_collection(
        collection_name=name,
        vectors_config={DENSE_VECTOR: models.VectorParams(size=settings.embed_dimension, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE_VECTOR: models.SparseVectorParams(index=models.SparseIndexParams(on_disk=True))},
        on_disk_payload=True,
    )


async def delete_collection(kb_id: str) -> None:
    name = collection_name(kb_id)
    if await get_client().collection_exists(name):
        await get_client().delete_collection(name)


async def upsert_chunks(kb_id: str, chunks: list[ChunkVector]) -> None:
    if not chunks:
        return
    await create_collection(kb_id)
    points = [
        models.PointStruct(
            id=chunk.id,
            vector={
                DENSE_VECTOR: chunk.dense,
                SPARSE_VECTOR: models.SparseVector(indices=list(chunk.sparse), values=list(chunk.sparse.values())),
            },
            payload=chunk.payload,
        )
        for chunk in chunks
    ]
    for start in range(0, len(points), _BATCH_SIZE):
        await get_client().upsert(collection_name=collection_name(kb_id), points=points[start:start + _BATCH_SIZE], wait=True)


def _filter(filters: dict | None) -> models.Filter | None:
    if not filters:
        return None
    return models.Filter(must=[models.FieldCondition(key=key, match=models.MatchValue(value=value)) for key, value in filters.items()])


async def hybrid_search(
    kb_id: str,
    query_dense: list[float],
    query_sparse: dict[int, float],
    top_k: int = 5,
    score_threshold: float = 0.3,
    filters: dict | None = None,
    search_type: str = "hybrid",
) -> list[models.ScoredPoint]:
    sparse = models.SparseVector(indices=list(query_sparse), values=list(query_sparse.values()))
    common = {"collection_name": collection_name(kb_id), "query_filter": _filter(filters), "limit": top_k, "with_payload": True, "score_threshold": score_threshold}
    if search_type == "dense":
        result = await get_client().query_points(query=query_dense, using=DENSE_VECTOR, **common)
    elif search_type == "sparse":
        result = await get_client().query_points(query=sparse, using=SPARSE_VECTOR, **common)
    else:
        prefetch = [
            models.Prefetch(query=query_dense, using=DENSE_VECTOR, limit=max(top_k * 4, 20), filter=_filter(filters)),
            models.Prefetch(query=sparse, using=SPARSE_VECTOR, limit=max(top_k * 4, 20), filter=_filter(filters)),
        ]
        result = await get_client().query_points(
            collection_name=collection_name(kb_id),
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
            score_threshold=score_threshold,
        )
    return result.points


async def count_above_threshold(
    kb_id: str,
    query_dense: list[float],
    query_sparse: dict[int, float],
    score_threshold: float,
    search_type: str = "hybrid",
) -> int:
    return len(await hybrid_search(kb_id, query_dense, query_sparse, top_k=1000, score_threshold=score_threshold, search_type=search_type))


async def delete_chunks_by_document(kb_id: str, document_id: str) -> None:
    await get_client().delete(
        collection_name=collection_name(kb_id),
        points_selector=models.FilterSelector(
            filter=models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])
        ),
        wait=True,
    )


async def get_collection_info(kb_id: str) -> dict:
    info = await get_client().get_collection(collection_name(kb_id))
    return {"vectors_count": info.points_count, "status": str(info.status), "config": info.config.model_dump(mode="json")}

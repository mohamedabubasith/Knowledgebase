"""
Search engine — hybrid, vector-only, or lexical-only.
Qdrant + Postgres FTS run concurrently via asyncio.gather.
In-process TTL cache for repeat queries (zero-copy dict lookup).
"""
import asyncio
import time
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.registry import registry
from app.db.models import Chunk, Document
from app.db.session import get_session_factory
from app.embedding.embedder import embed_single
from app.models.schemas import SearchResponse, SearchResultItem
from app.vectorstore import get_vector_store

log = structlog.get_logger(__name__)

# ── In-process TTL cache ──────────────────────────────────────────────────────
_cache: dict[str, tuple[float, SearchResponse]] = {}
_cache_lock = asyncio.Lock()


def _cache_key(query: str, mode: str, tenant_id: str, top_k: int, document_id: Optional[str]) -> str:
    return f"{tenant_id}:{mode}:{top_k}:{document_id or ''}:{query}"


async def _cache_get(key: str) -> Optional[SearchResponse]:
    if settings.search_cache_ttl <= 0:
        return None
    async with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.monotonic() - entry[0]) < settings.search_cache_ttl:
            return entry[1]
        if entry:
            del _cache[key]
    return None


async def _cache_set(key: str, response: SearchResponse) -> None:
    if settings.search_cache_ttl <= 0:
        return
    async with _cache_lock:
        if len(_cache) >= settings.search_cache_max:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            del _cache[oldest]
        _cache[key] = (time.monotonic(), response)


# ── Main search entrypoint ────────────────────────────────────────────────────

async def search(
    query: str,
    tenant_id: str,
    mode: str = "hybrid",
    top_k: int = 10,
    min_score: float = 0.0,
    document_id: Optional[str] = None,
) -> SearchResponse:
    t0 = time.monotonic()
    cache_key = _cache_key(query, mode, tenant_id, top_k, document_id)

    cached = await _cache_get(cache_key)
    if cached:
        return cached

    effective_mode = _resolve_mode(mode)

    if effective_mode == "hybrid":
        results, used_mode = await _hybrid_search(query, tenant_id, top_k, document_id)
    elif effective_mode == "vector_only":
        results, used_mode = await _vector_search(query, tenant_id, top_k, document_id)
    elif effective_mode == "lexical_only":
        results, used_mode = await _fts_search(query, tenant_id, top_k, document_id)
    else:
        results, used_mode = await _keyword_search(query, tenant_id, top_k, document_id)

    # Apply min_score filter
    if min_score > 0.0:
        results = [r for r in results if r.score >= min_score]

    response = SearchResponse(
        results=results,
        total=len(results),
        search_mode_used=used_mode,
        query_ms=round((time.monotonic() - t0) * 1000, 2),
        query=query,
    )
    await _cache_set(cache_key, response)
    return response


def _resolve_mode(requested: str) -> str:
    if registry.search_mode == "fts_only":
        return "lexical_only"
    return requested


# ── Hybrid search ─────────────────────────────────────────────────────────────

async def _hybrid_search(
    query: str,
    tenant_id: str,
    top_k: int,
    document_id: Optional[str],
) -> tuple[list[SearchResultItem], str]:
    query_vector, fts_rows = await asyncio.gather(
        embed_single(query),
        _run_fts(query, tenant_id, top_k * 2, document_id),
    )

    vector_hits = await get_vector_store().search(query_vector, tenant_id, top_k * 2, document_id)

    scores: dict[str, float] = {}
    vector_payloads: dict[str, dict] = {}

    for hit in vector_hits:
        scores[hit.point_id] = settings.hybrid_vector_weight * hit.score
        vector_payloads[hit.point_id] = hit.payload

    for row in fts_rows:
        cid = str(row.id)
        lexical = settings.hybrid_lexical_weight * float(row.rank)
        scores[cid] = scores.get(cid, 0.0) + lexical
        if cid not in vector_payloads:
            vector_payloads[cid] = {}

    sorted_ids = sorted(scores, key=lambda k: scores[k], reverse=True)[:top_k]

    chunks = await _fetch_chunks_by_ids(sorted_ids, tenant_id)
    chunk_map = {str(c.id): c for c in chunks}

    results = []
    for cid in sorted_ids:
        c = chunk_map.get(cid)
        if not c:
            continue
        results.append(SearchResultItem(
            chunk_id=cid,
            document_id=str(c.document_id),
            text=c.chunk_text,
            score=round(scores[cid], 6),
            page_number=c.page_number,
            file_path=c.minio_path,
            filename=c.filename,
        ))

    return results, "hybrid"


# ── Vector-only search ────────────────────────────────────────────────────────

async def _vector_search(
    query: str,
    tenant_id: str,
    top_k: int,
    document_id: Optional[str],
) -> tuple[list[SearchResultItem], str]:
    query_vector = await embed_single(query)
    hits = await get_vector_store().search(query_vector, tenant_id, top_k, document_id)

    ids = [h.point_id for h in hits]
    score_map = {h.point_id: h.score for h in hits}
    chunks = await _fetch_chunks_by_ids(ids, tenant_id)
    chunk_map = {str(c.id): c for c in chunks}

    results = [
        SearchResultItem(
            chunk_id=cid,
            document_id=str(chunk_map[cid].document_id),
            text=chunk_map[cid].chunk_text,
            score=round(score_map[cid], 6),
            page_number=chunk_map[cid].page_number,
            file_path=chunk_map[cid].minio_path,
            filename=chunk_map[cid].filename,
        )
        for cid in ids if cid in chunk_map
    ]
    return results, "vector_only"


# ── Lexical-only search ───────────────────────────────────────────────────────

async def _fts_search(
    query: str,
    tenant_id: str,
    top_k: int,
    document_id: Optional[str],
) -> tuple[list[SearchResultItem], str]:
    rows = await _run_fts(query, tenant_id, top_k, document_id)

    results = [
        SearchResultItem(
            chunk_id=str(r.id),
            document_id=str(r.document_id),
            text=r.chunk_text,
            score=round(float(r.rank), 6),
            page_number=r.page_number,
            file_path=r.minio_path,
            filename=r.filename,
        )
        for r in rows
    ]
    return results, "lexical_only"


# ── Keyword fallback (last resort) ────────────────────────────────────────────

async def _keyword_search(
    query: str,
    tenant_id: str,
    top_k: int,
    document_id: Optional[str],
) -> tuple[list[SearchResultItem], str]:
    factory = get_session_factory()
    stmt = (
        select(Chunk.id, Chunk.document_id, Chunk.chunk_text, Chunk.page_number, Document.minio_path)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.chunk_text.ilike(f"%{query}%"),
            Chunk.tenant_id == tenant_id,
        )
        .limit(top_k)
    )
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)

    async with factory() as session:
        rows = (await session.execute(stmt)).all()

    results = [
        SearchResultItem(
            chunk_id=str(r.id),
            document_id=str(r.document_id),
            text=r.chunk_text,
            score=0.0,
            page_number=r.page_number,
            file_path=r.minio_path,
        )
        for r in rows
    ]
    return results, "keyword_fallback"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _run_fts(
    query: str,
    tenant_id: str,
    top_k: int,
    document_id: Optional[str],
):
    fts_query = func.websearch_to_tsquery("english", query)
    rank_expr = func.ts_rank_cd(Chunk.fts_vector, fts_query, 32).label("rank")

    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.chunk_text,
            Chunk.page_number,
            Document.minio_path,
            Document.filename,
            rank_expr,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.fts_vector.op("@@")(fts_query),
            Chunk.tenant_id == tenant_id,
        )
        .order_by(rank_expr.desc())
        .limit(top_k)
    )
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)

    factory = get_session_factory()
    async with factory() as session:
        return (await session.execute(stmt)).all()


async def _fetch_chunks_by_ids(ids: list[str], tenant_id: str):
    if not ids:
        return []
    factory = get_session_factory()
    stmt = (
        select(Chunk.id, Chunk.document_id, Chunk.chunk_text, Chunk.page_number,
               Document.minio_path, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(ids), Chunk.tenant_id == tenant_id)
    )
    async with factory() as session:
        return (await session.execute(stmt)).all()

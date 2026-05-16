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
from app.search.tabular_engine import query_tabular

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

    # Enrich tabular results with DuckDB NL2SQL answers
    results = await _enrich_tabular_results(query, results)

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
        is_tab = getattr(c, "is_tabular", False) or False
        results.append(SearchResultItem(
            chunk_id=cid,
            document_id=str(c.document_id),
            text=c.chunk_text,
            score=round(scores[cid], 6),
            page_number=c.page_number,
            file_path=c.minio_path,
            filename=c.filename,
            result_type="tabular" if is_tab else "text",
            table_schema=c.table_schema if is_tab else None,
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

    results = []
    for cid in ids:
        c = chunk_map.get(cid)
        if not c:
            continue
        is_tab = getattr(c, "is_tabular", False) or False
        results.append(SearchResultItem(
            chunk_id=cid,
            document_id=str(c.document_id),
            text=c.chunk_text,
            score=round(score_map[cid], 6),
            page_number=c.page_number,
            file_path=c.minio_path,
            filename=c.filename,
            result_type="tabular" if is_tab else "text",
            table_schema=c.table_schema if is_tab else None,
        ))
    return results, "vector_only"


# ── Lexical-only search ───────────────────────────────────────────────────────

async def _fts_search(
    query: str,
    tenant_id: str,
    top_k: int,
    document_id: Optional[str],
) -> tuple[list[SearchResultItem], str]:
    rows = await _run_fts(query, tenant_id, top_k, document_id)

    results = []
    for r in rows:
        is_tab = getattr(r, "is_tabular", False) or False
        results.append(SearchResultItem(
            chunk_id=str(r.id),
            document_id=str(r.document_id),
            text=r.chunk_text,
            score=round(float(r.rank), 6),
            page_number=r.page_number,
            file_path=r.minio_path,
            filename=r.filename,
            result_type="tabular" if is_tab else "text",
            table_schema=r.table_schema if is_tab else None,
        ))
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
        select(
            Chunk.id, Chunk.document_id, Chunk.chunk_text, Chunk.page_number,
            Document.minio_path, Document.filename,
            Document.is_tabular, Document.table_schema,
        )
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

    results = []
    for r in rows:
        is_tab = getattr(r, "is_tabular", False) or False
        results.append(SearchResultItem(
            chunk_id=str(r.id),
            document_id=str(r.document_id),
            text=r.chunk_text,
            score=0.0,
            page_number=r.page_number,
            file_path=r.minio_path,
            filename=r.filename,
            result_type="tabular" if is_tab else "text",
            table_schema=r.table_schema if is_tab else None,
        ))
    return results, "keyword_fallback"


# ── Helpers ───────────────────────────────────────────────────────────────────

# Question/stop words stripped before FTS — they produce empty tsquery lexemes
_QUESTION_WORDS = frozenset({
    "what", "where", "when", "who", "which", "how", "why", "is", "are",
    "was", "were", "does", "do", "did", "can", "could", "would", "should",
    "the", "a", "an", "in", "on", "of", "for", "to", "and", "or", "not",
    "it", "its", "that", "this", "these", "those", "there", "their",
    "my", "your", "our", "by", "at", "with", "from", "has", "have", "had",
    "been", "be", "will", "shall", "may", "might", "must", "need",
})


def _clean_fts_query(query: str) -> str:
    """Strip question/stop words so FTS tsquery has meaningful lexemes."""
    tokens = [w.strip("?!.,;:'\"") for w in query.lower().split()]
    meaningful = [t for t in tokens if t and t not in _QUESTION_WORDS and len(t) > 1]
    return " ".join(meaningful) if meaningful else query


def _or_fts_query(query: str) -> str:
    """Build OR-joined websearch query — any term matches (high recall)."""
    tokens = [w.strip("?!.,;:'\"") for w in query.lower().split()]
    meaningful = [t for t in tokens if t and t not in _QUESTION_WORDS and len(t) > 1]
    return " OR ".join(meaningful) if meaningful else query


async def _run_fts(
    query: str,
    tenant_id: str,
    top_k: int,
    document_id: Optional[str],
):
    """Three-pass FTS strategy (precision → recall):
    1. websearch_to_tsquery on cleaned query — AND logic, high precision
    2. plainto_tsquery on cleaned query    — AND logic, handles operators as literals
    3. websearch_to_tsquery with OR terms  — OR logic, high recall for NL questions
    """
    cleaned = _clean_fts_query(query)
    or_query = _or_fts_query(query)

    factory = get_session_factory()

    async def _exec_fts(q: str) -> list:
        fts_q = func.websearch_to_tsquery("english", q)
        rank_expr = func.ts_rank_cd(Chunk.fts_vector, fts_q, 32).label("rank")
        stmt = (
            select(
                Chunk.id,
                Chunk.document_id,
                Chunk.chunk_text,
                Chunk.page_number,
                Document.minio_path,
                Document.filename,
                Document.is_tabular,
                Document.table_schema,
                rank_expr,
            )
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.fts_vector.op("@@")(fts_q),
                Chunk.tenant_id == tenant_id,
            )
            .order_by(rank_expr.desc())
            .limit(top_k)
        )
        if document_id:
            stmt = stmt.where(Chunk.document_id == document_id)
        async with factory() as session:
            return (await session.execute(stmt)).all()

    # Pass 1 — AND on cleaned query (strip question words, high precision)
    rows = await _exec_fts(cleaned)

    # Pass 2 — AND on original query (fallback if cleaning removed too much)
    if not rows:
        rows = await _exec_fts(query)

    # Pass 3 — OR on cleaned tokens (high recall, catches partial matches)
    # websearch_to_tsquery treats "word1 OR word2" as OR logic
    if not rows:
        rows = await _exec_fts(or_query)

    return rows


async def _fetch_chunks_by_ids(ids: list[str], tenant_id: str):
    if not ids:
        return []
    factory = get_session_factory()
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.chunk_text,
            Chunk.page_number,
            Document.minio_path,
            Document.filename,
            Document.is_tabular,
            Document.table_schema,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(ids), Chunk.tenant_id == tenant_id)
    )
    async with factory() as session:
        return (await session.execute(stmt)).all()


# ── Tabular result enrichment ─────────────────────────────────────────────────

async def _enrich_tabular_results(
    query: str,
    results: list[SearchResultItem],
) -> list[SearchResultItem]:
    """
    For each result that came from a tabular document, run NL2SQL via DuckDB
    and replace the generic summary chunk text with the actual query answer.

    Non-tabular results are returned unchanged.
    Errors are logged and the original summary text is kept as fallback.
    """
    tabular_indices = [
        i for i, r in enumerate(results)
        if r.table_schema is not None
    ]
    if not tabular_indices:
        return results

    async def _enrich_one(idx: int) -> None:
        r = results[idx]
        try:
            sql, md = await query_tabular(
                query=query,
                document_id=r.document_id,
                minio_path=r.file_path,
                table_schema=r.table_schema,
                filename=r.filename or "",
            )
            results[idx] = r.model_copy(update={
                "text":        md,
                "result_type": "tabular",
                "sql_query":   sql,
            })
        except Exception as exc:
            log.error("tabular_enrichment_error", document_id=r.document_id, error=str(exc))
            # Keep original summary text — still useful context

    await asyncio.gather(*[_enrich_one(i) for i in tabular_indices])
    return results

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


# ── Ingest ───────────────────────────────────────────────
class IngestResponse(BaseModel):
    document_id: str
    status: str
    message: str


# ── Documents ────────────────────────────────────────────
class DocumentOut(BaseModel):
    id: str
    tenant_id: str
    filename: str
    mime_type: str
    minio_path: str
    file_size: Optional[int]
    parse_mode: Optional[str]
    status: str
    page_count: Optional[int]
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    id: str
    chunk_index: int
    chunk_text: str
    token_count: int
    page_number: Optional[int]
    checksum: str


# ── Search ───────────────────────────────────────────────
class SearchMode(str, Enum):
    hybrid = "hybrid"
    """Combines vector similarity + full-text search (BM25). Best overall quality. Recommended default."""
    vector_only = "vector_only"
    """Pure semantic/vector search. Great for conceptual, paraphrased, or multilingual queries."""
    lexical_only = "lexical_only"
    """Pure full-text keyword search (BM25/FTS). Fast. Best for exact terms, codes, IDs."""


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Search query text")
    mode: SearchMode = Field(
        default=SearchMode.hybrid,
        description=(
            "Search strategy:\n"
            "- **hybrid** — vector + keyword combined (best quality, recommended)\n"
            "- **vector_only** — semantic/conceptual search (good for paraphrases)\n"
            "- **lexical_only** — exact keyword match (fast, good for IDs/codes)"
        ),
    )
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to return")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum relevance score threshold (0=no filter)")
    document_id: Optional[str] = Field(default=None, description="Scope search to a specific document")


class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float
    page_number: Optional[int]
    file_path: str
    filename: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    search_mode_used: str
    query_ms: float
    query: str


# ── Health ───────────────────────────────────────────────
class ComponentHealth(BaseModel):
    status: Literal["ok", "degraded", "down"]
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    registry: dict
    components: dict[str, ComponentHealth]

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


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
class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float
    page_number: Optional[int]
    file_path: str


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    search_mode_used: str
    query_ms: float


# ── Health ───────────────────────────────────────────────
class ComponentHealth(BaseModel):
    status: Literal["ok", "degraded", "down"]
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    registry: dict
    components: dict[str, ComponentHealth]

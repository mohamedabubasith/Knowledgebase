from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID


@dataclass
class ParsedDocument:
    raw_text: str
    pages: list[dict]          # [{page_number: int, text: str}]
    parse_mode: str
    char_count: int
    checksum: str              # sha256(raw_text)


@dataclass
class Chunk:
    chunk_index: int
    text: str
    token_count: int
    page_number: Optional[int]
    start_char: int
    end_char: int
    checksum: str              # sha256(text)


@dataclass
class EmbeddedChunk:
    chunk: Chunk
    vector: list[float]


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    tenant_id: str
    text: str
    score: float
    page_number: Optional[int]
    file_path: str
    parse_mode: str
    search_mode_used: str

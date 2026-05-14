"""
Token-based sliding window chunker.
- tiktoken cl100k_base (deterministic, CPU-only)
- Page-boundary aware: chunks never span pages when page data available
- Min chunk: 64 tokens (noise filter)
- Integrity enforced: start_char + len(text) == end_char
"""
import hashlib
from typing import Optional

import tiktoken

from app.models.domain import Chunk, ParsedDocument

_TOKENIZER = tiktoken.get_encoding("cl100k_base")

CHUNK_SIZE = 512
CHUNK_OVERLAP = 128       # 25%
CHUNK_STRIDE = CHUNK_SIZE - CHUNK_OVERLAP
MIN_CHUNK_TOKENS = 64


class ChunkIntegrityError(Exception):
    pass


def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    if not doc.raw_text.strip():
        return []

    if doc.pages:
        return _chunk_with_pages(doc)
    return _chunk_flat(doc.raw_text, page_number=None)


def _chunk_flat(text: str, page_number: Optional[int]) -> list[Chunk]:
    token_ids = _TOKENIZER.encode(text)
    offsets = _build_char_offsets(text, token_ids)
    return _sliding_window(text, token_ids, offsets, page_number, chunk_index_start=0)


def _chunk_with_pages(doc: ParsedDocument) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    chunk_index = 0

    for page in doc.pages:
        page_chunks = _chunk_flat(page["text"], page_number=page["page_number"])
        for c in page_chunks:
            # Re-index sequentially across all pages
            all_chunks.append(
                Chunk(
                    chunk_index=chunk_index,
                    text=c.text,
                    token_count=c.token_count,
                    page_number=c.page_number,
                    start_char=c.start_char,
                    end_char=c.end_char,
                    checksum=c.checksum,
                )
            )
            chunk_index += 1

    return all_chunks


def _build_char_offsets(text: str, token_ids: list[int]) -> list[tuple[int, int]]:
    """Map each token index → (start_char, end_char) in original text."""
    offsets = []
    pos = 0
    for tid in token_ids:
        token_bytes = _TOKENIZER.decode_single_token_bytes(tid)
        token_str = token_bytes.decode("utf-8", errors="replace")
        start = text.find(token_str, pos)
        if start == -1:
            start = pos
        end = start + len(token_str)
        offsets.append((start, end))
        pos = end
    return offsets


def _sliding_window(
    text: str,
    token_ids: list[int],
    offsets: list[tuple[int, int]],
    page_number: Optional[int],
    chunk_index_start: int,
) -> list[Chunk]:
    chunks = []
    n = len(token_ids)
    i = 0
    chunk_index = chunk_index_start

    while i < n:
        end = min(i + CHUNK_SIZE, n)
        window_tokens = token_ids[i:end]

        if len(window_tokens) < MIN_CHUNK_TOKENS:
            break

        start_char = offsets[i][0]
        end_char = offsets[end - 1][1]
        chunk_text = text[start_char:end_char]

        # Integrity check
        if start_char + len(chunk_text) != end_char:
            raise ChunkIntegrityError(
                f"Chunk integrity fail: start={start_char} len={len(chunk_text)} end={end_char}"
            )

        chunks.append(
            Chunk(
                chunk_index=chunk_index,
                text=chunk_text,
                token_count=len(window_tokens),
                page_number=page_number,
                start_char=start_char,
                end_char=end_char,
                checksum=hashlib.sha256(chunk_text.encode()).hexdigest(),
            )
        )
        chunk_index += 1
        i += CHUNK_STRIDE

    return chunks

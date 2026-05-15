"""
Token-based sliding window chunker.
- tiktoken cl100k_base (deterministic, CPU-only)
- Page-boundary aware: chunks never span pages when page data available
- Chunk size driven by EMBEDDING_MAX_TOKENS env var (default 96)
- Integrity enforced: start_char + len(text) == end_char
"""
import hashlib
from typing import Optional

import tiktoken

from app.core.config import settings
from app.models.domain import Chunk, ParsedDocument

_TOKENIZER = tiktoken.get_encoding("cl100k_base")

# Chunk size is set to the embedding model's token limit (from env).
# 25% overlap; min chunk = max(16, size // 6) to filter noise.
CHUNK_SIZE    = settings.embedding_max_tokens
CHUNK_OVERLAP = max(8, CHUNK_SIZE // 4)        # 25%
CHUNK_STRIDE  = CHUNK_SIZE - CHUNK_OVERLAP
MIN_CHUNK_TOKENS = max(16, CHUNK_SIZE // 6)


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
    """Map each token index → (start_char, end_char) in original text.

    tiktoken operates on UTF-8 bytes. We track byte positions then convert to
    char positions via a one-time byte→char lookup table so multi-byte UTF-8
    characters (CJK, Arabic, emoji, etc.) are handled correctly even when a
    token straddles a character boundary.
    """
    text_bytes = text.encode("utf-8")
    n_bytes = len(text_bytes)
    n_chars = len(text)

    # Build byte_pos → char_pos table (length n_bytes + 1, last entry = n_chars).
    # Every byte that belongs to the same multi-byte sequence maps to the same
    # char index; the sentinel at n_bytes maps to n_chars.
    byte_to_char: list[int] = [0] * (n_bytes + 1)
    char_idx = 0
    b = 0
    while b < n_bytes:
        bval = text_bytes[b]
        if bval < 0x80:
            seq_len = 1
        elif bval < 0xE0:
            seq_len = 2
        elif bval < 0xF0:
            seq_len = 3
        else:
            seq_len = 4
        for k in range(seq_len):
            if b + k < n_bytes:
                byte_to_char[b + k] = char_idx
        b += seq_len
        char_idx += 1
    byte_to_char[n_bytes] = n_chars  # sentinel

    offsets: list[tuple[int, int]] = []
    byte_pos = 0
    for tid in token_ids:
        token_bytes = _TOKENIZER.decode_single_token_bytes(tid)
        start_byte = byte_pos
        end_byte = byte_pos + len(token_bytes)

        start_char = byte_to_char[min(start_byte, n_bytes)]

        # If end_byte lands inside a continuation byte sequence, advance to the
        # next character boundary so the slice text[start_char:end_char] is
        # always a valid substring (integrity check: len == end - start).
        eb = min(end_byte, n_bytes)
        while eb < n_bytes and 0x80 <= text_bytes[eb] < 0xC0:
            eb += 1
        end_char = byte_to_char[eb] if eb < n_bytes else n_chars

        offsets.append((start_char, end_char))
        byte_pos = end_byte  # advance by actual token byte length

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

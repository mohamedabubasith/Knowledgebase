"""
Tests for token-based sliding window chunker.
No external dependencies — tiktoken runs for real.
"""
import hashlib

import pytest

from app.ingestion.chunker import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MIN_CHUNK_TOKENS,
    chunk_document,
    _chunk_flat,
    _chunk_with_pages,
)
from app.models.domain import ParsedDocument


def _make_doc(text: str, pages=None) -> ParsedDocument:
    return ParsedDocument(
        raw_text=text,
        pages=pages or [],
        parse_mode="plain_text",
        char_count=len(text),
        checksum=hashlib.sha256(text.encode()).hexdigest(),
    )


def _long_text(n_words: int = 600) -> str:
    return " ".join(f"word{i}" for i in range(n_words))


class TestChunkDocument:

    def test_empty_text_returns_no_chunks(self):
        doc = _make_doc("")
        assert chunk_document(doc) == []

    def test_whitespace_only_returns_no_chunks(self):
        doc = _make_doc("   \n\t  ")
        assert chunk_document(doc) == []

    def test_short_text_below_min_tokens_returns_no_chunks(self):
        # 5 words << MIN_CHUNK_TOKENS (64)
        doc = _make_doc("hello world foo bar baz")
        assert chunk_document(doc) == []

    def test_single_page_produces_chunks(self):
        doc = _make_doc(_long_text(600))
        chunks = chunk_document(doc)
        assert len(chunks) >= 1

    def test_chunk_indices_are_sequential(self):
        doc = _make_doc(_long_text(600))
        chunks = chunk_document(doc)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_chunk_text_is_verbatim_slice(self):
        text = _long_text(600)
        doc = _make_doc(text)
        chunks = chunk_document(doc)
        for c in chunks:
            assert text[c.start_char:c.end_char] == c.text

    def test_chunk_checksum_matches_text(self):
        doc = _make_doc(_long_text(600))
        chunks = chunk_document(doc)
        for c in chunks:
            expected = hashlib.sha256(c.text.encode()).hexdigest()
            assert c.checksum == expected, f"Chunk {c.chunk_index} checksum mismatch"

    def test_chunk_token_count_within_bounds(self):
        doc = _make_doc(_long_text(600))
        chunks = chunk_document(doc)
        for c in chunks:
            assert c.token_count <= CHUNK_SIZE
            assert c.token_count >= MIN_CHUNK_TOKENS

    def test_overlap_chunks_share_text(self):
        """Adjacent chunks share CHUNK_OVERLAP tokens — their text overlaps."""
        doc = _make_doc(_long_text(1200))
        chunks = chunk_document(doc)
        if len(chunks) < 2:
            pytest.skip("Not enough chunks to test overlap")
        # Text of chunk[1] should START within the END of chunk[0]
        c0_end = chunks[0].end_char
        c1_start = chunks[1].start_char
        assert c1_start < c0_end, "No overlap between adjacent chunks"

    def test_page_aware_chunking_assigns_page_numbers(self):
        pages = [
            {"page_number": 1, "text": _long_text(200)},
            {"page_number": 2, "text": _long_text(200)},
        ]
        doc = _make_doc("\n".join(p["text"] for p in pages), pages=pages)
        chunks = chunk_document(doc)
        page_nums = {c.page_number for c in chunks}
        assert page_nums <= {1, 2}
        assert None not in page_nums

    def test_no_page_data_sets_page_number_none(self):
        doc = _make_doc(_long_text(600))
        chunks = chunk_document(doc)
        assert all(c.page_number is None for c in chunks)

    def test_deterministic_output(self):
        """Same input always produces identical chunks."""
        text = _long_text(800)
        doc1 = _make_doc(text)
        doc2 = _make_doc(text)
        chunks1 = chunk_document(doc1)
        chunks2 = chunk_document(doc2)
        assert len(chunks1) == len(chunks2)
        for a, b in zip(chunks1, chunks2):
            assert a.checksum == b.checksum

    def test_start_end_chars_non_overlapping_within_chunk(self):
        doc = _make_doc(_long_text(600))
        chunks = chunk_document(doc)
        for c in chunks:
            assert c.start_char < c.end_char

    def test_unicode_text_does_not_crash(self):
        unicode_text = "مرحبا بالعالم " * 100 + "Hello world " * 100
        doc = _make_doc(unicode_text)
        # Should not raise; may produce 0 or more chunks
        chunks = chunk_document(doc)
        for c in chunks:
            assert c.checksum == hashlib.sha256(c.text.encode()).hexdigest()

"""
Local PDF parser using PyMuPDF (fitz) — 5-10x faster than pdfminer.
No OCR. Scanned PDFs return empty text per page (handled upstream).
"""
import hashlib
import io
import structlog

from app.models.domain import ParsedDocument

log = structlog.get_logger(__name__)


def parse(data: bytes) -> ParsedDocument:
    import fitz  # PyMuPDF

    pages = []
    all_texts = []

    doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text").strip()
            if text:
                pages.append({"page_number": page_num + 1, "text": text})
                all_texts.append(text)
    finally:
        doc.close()

    raw_text = "\n".join(all_texts)
    return ParsedDocument(
        raw_text=raw_text,
        pages=pages,
        parse_mode="pymupdf",
        char_count=len(raw_text),
        checksum=hashlib.sha256(raw_text.encode()).hexdigest(),
    )

"""
Self-hosted Unstructured container parser.
Used when UNSTRUCTURED_LOCAL_URL is reachable (fallback to local parsers if not).
Handles OCR for scanned PDFs via Unstructured's built-in support.
"""
import hashlib
import httpx
import structlog

from app.core.config import settings
from app.models.domain import ParsedDocument
from app.parsers.unstructured import _elements_to_document

log = structlog.get_logger(__name__)


async def parse(filename: str, data: bytes, mime_type: str, strategy: str = "fast") -> ParsedDocument:
    strategy = strategy if strategy in ("fast", "hi_res", "ocr_only", "auto") else "fast"
    async with httpx.AsyncClient(timeout=600.0) as client:
        r = await client.post(
            f"{settings.unstructured_local_url}/general/v0/general",
            files={"files": (filename, data, mime_type)},
            data={
                "strategy": strategy,
                "include_page_breaks": "true",
            },
        )
        r.raise_for_status()

    elements = r.json()
    doc = _elements_to_document(elements)
    # Override parse_mode to distinguish from cloud
    doc = ParsedDocument(
        raw_text=doc.raw_text,
        pages=doc.pages,
        parse_mode="local_unstructured",
        char_count=doc.char_count,
        checksum=doc.checksum,
    )
    return doc

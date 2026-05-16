"""
Parser router — selects parser based on MIME type + registry backend.
Async wrappers run blocking parsers in ProcessPoolExecutor.
"""
import asyncio
import structlog
from concurrent.futures import ProcessPoolExecutor

from app.core.registry import registry
from app.models.domain import ParsedDocument

log = structlog.get_logger(__name__)

_process_pool: ProcessPoolExecutor | None = None


def init_parser_pool(max_workers: int) -> None:
    global _process_pool
    _process_pool = ProcessPoolExecutor(max_workers=max_workers)
    log.info("parser_process_pool_ready", workers=max_workers)


def _get_pool() -> ProcessPoolExecutor:
    if _process_pool is None:
        raise RuntimeError("Parser pool not initialized")
    return _process_pool


# ── CPU-bound parse functions (run in subprocess) ────────────────────────────

def _parse_pdf(data: bytes) -> ParsedDocument:
    from app.parsers.pdf import parse
    return parse(data)


def _parse_docx(data: bytes) -> ParsedDocument:
    from app.parsers.docx import parse
    return parse(data)


def _parse_html(data: bytes) -> ParsedDocument:
    from app.parsers.html import parse
    return parse(data)


def _parse_plain(data: bytes) -> ParsedDocument:
    from app.parsers.plain import parse
    return parse(data)


# ── Async dispatcher ─────────────────────────────────────────────────────────

async def parse_document(
    filename: str,
    data: bytes,
    mime_type: str,
    parsing_strategy: str = "fast",
) -> ParsedDocument:
    """
    Route to correct parser based on registry.parse_backend + mime_type.
    Unstructured (API or local) handles all types including scanned PDFs.
    Local parsers handle text-layer content only.
    """
    assert registry.is_frozen(), "Registry must be frozen before parsing"

    backend = registry.parse_backend
    loop = asyncio.get_event_loop()

    # Unstructured paths — async HTTP, no process pool needed
    if backend == "unstructured_api":
        from app.parsers.unstructured import parse as _parse
        try:
            return await _parse(filename, data, mime_type, strategy=parsing_strategy)
        except Exception as e:
            log.error("unstructured_api_parse_failed", error=str(e), filename=filename)
            raise

    if backend == "local_unstructured":
        from app.parsers.local_unstructured import parse as _parse
        try:
            return await _parse(filename, data, mime_type, strategy=parsing_strategy)
        except Exception as e:
            log.error("local_unstructured_parse_failed", error=str(e), filename=filename)
            raise

    # Local parsers — CPU-bound, run in process pool
    normalized = mime_type.lower().split(";")[0].strip()

    if normalized == "application/pdf":
        fn = _parse_pdf
    elif normalized in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        fn = _parse_docx
    elif normalized in ("text/html", "application/xhtml+xml"):
        fn = _parse_html
    elif normalized in ("text/plain", "text/markdown", "text/x-markdown"):
        fn = _parse_plain
    else:
        # Unknown type — try plain text
        log.warning("unknown_mime_fallback_plain", mime=mime_type, filename=filename)
        fn = _parse_plain

    return await loop.run_in_executor(_get_pool(), fn, data)

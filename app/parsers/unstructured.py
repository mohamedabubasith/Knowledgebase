"""
Unstructured cloud API parser.
Used when UNSTRUCTURED_API_URL is set and reachable.
"""
import hashlib
import httpx
import structlog

from app.core.config import settings
from app.models.domain import ParsedDocument

log = structlog.get_logger(__name__)


async def parse(filename: str, data: bytes, mime_type: str) -> ParsedDocument:
    headers = {"unstructured-api-key": settings.unstructured_api_key} if settings.unstructured_api_key else {}

    async with httpx.AsyncClient(timeout=600.0) as client:
        r = await client.post(
            f"{settings.unstructured_api_url}/general/v0/general",
            headers=headers,
            files={"files": (filename, data, mime_type)},
            data={
                "strategy": "fast",
                "include_page_breaks": "true",
            },
        )
        r.raise_for_status()

    elements = r.json()
    return _elements_to_document(elements)


def _elements_to_document(elements: list[dict]) -> ParsedDocument:
    pages: dict[int, list[str]] = {}
    all_texts: list[str] = []

    for el in elements:
        text = el.get("text", "").strip()
        if not text:
            continue
        all_texts.append(text)
        page_num = el.get("metadata", {}).get("page_number")
        if page_num is not None:
            pages.setdefault(page_num, []).append(text)

    raw_text = "\n".join(all_texts)
    pages_list = [
        {"page_number": pn, "text": "\n".join(txts)}
        for pn, txts in sorted(pages.items())
    ]

    return ParsedDocument(
        raw_text=raw_text,
        pages=pages_list,
        parse_mode="unstructured_api",
        char_count=len(raw_text),
        checksum=hashlib.sha256(raw_text.encode()).hexdigest(),
    )

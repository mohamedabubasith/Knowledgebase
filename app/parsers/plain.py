import hashlib

from app.models.domain import ParsedDocument


def parse(data: bytes) -> ParsedDocument:
    raw_text = data.decode("utf-8", errors="replace").strip()

    return ParsedDocument(
        raw_text=raw_text,
        pages=[],
        parse_mode="plain_text",
        char_count=len(raw_text),
        checksum=hashlib.sha256(raw_text.encode()).hexdigest(),
    )

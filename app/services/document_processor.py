import os
import tempfile

from unstructured.partition.auto import partition
from app.core.config import settings


def parse_document(path: str) -> str:
    return "\n\n".join(str(element).strip() for element in partition(filename=path) if str(element).strip())


def parse_document_bytes(data: bytes, filename: str) -> str:
    suffix = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix) as file:
        file.write(data)
        file.flush()
        return parse_document(file.name)


def chunk_text(text: str) -> list[str]:
    size, overlap = settings.chunk_size, settings.chunk_overlap
    if overlap >= size:
        raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
    chunks, start = [], 0
    separators = ["\n\n", "\n", ". ", " "]
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind(separator, start, end) for separator in separators)
            if cut > start:
                end = cut + 1
        value = text[start:end].strip()
        if value:
            chunks.append(value)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks

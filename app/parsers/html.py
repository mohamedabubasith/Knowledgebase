import hashlib

from app.models.domain import ParsedDocument


def parse(data: bytes) -> ParsedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    raw_text = soup.get_text(separator="\n", strip=True)

    return ParsedDocument(
        raw_text=raw_text,
        pages=[],
        parse_mode="beautifulsoup4",
        char_count=len(raw_text),
        checksum=hashlib.sha256(raw_text.encode()).hexdigest(),
    )

"""
Embedder — backend decided at startup, frozen.
Supports batch embedding for throughput.
ST model loaded once into memory at startup (if selected).
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
import structlog

from app.core.config import settings
from app.core.registry import registry

log = structlog.get_logger(__name__)

_st_model = None
_st_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embed")


def load_sentence_transformers() -> None:
    """Called at startup if ST backend selected. Loads model into memory once."""
    global _st_model
    import torch
    from sentence_transformers import SentenceTransformer

    torch.manual_seed(42)
    _st_model = SentenceTransformer(settings.st_model, device="cpu")
    # Warm-up pass to JIT compile
    _st_model.encode(["warmup"], batch_size=1, normalize_embeddings=True)
    log.info("sentence_transformers_loaded", model=settings.st_model, dim=registry.embed_dimension)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed list of texts. Returns list of float vectors.
    Batch size respects settings.embed_batch_size.
    """
    assert registry.is_frozen()

    if not texts:
        return []

    results: list[list[float]] = []
    batch_size = settings.embed_batch_size

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        if registry.embed_backend == "ollama":
            vecs = await _embed_ollama(batch)
        else:
            vecs = await _embed_st(batch)
        results.extend(vecs)

    return results


async def embed_single(text: str) -> list[float]:
    results = await embed_batch([text])
    return results[0]


async def _embed_ollama(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{settings.ollama_url}/api/embed",
            json={"model": settings.ollama_embed_model, "input": texts},
        )
        r.raise_for_status()
        data = r.json()
        return data["embeddings"]


async def _embed_st(texts: list[str]) -> list[list[float]]:
    if _st_model is None:
        raise RuntimeError("SentenceTransformers model not loaded")

    loop = asyncio.get_event_loop()

    def _encode():
        vecs = _st_model.encode(
            texts,
            batch_size=settings.embed_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vecs.tolist()

    return await loop.run_in_executor(_st_executor, _encode)

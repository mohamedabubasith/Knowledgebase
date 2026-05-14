"""
Startup probes — run ONCE before server accepts traffic.
Sets registry fields, then freezes. No retry after freeze.
"""
import asyncio
import structlog
import httpx

from app.core.config import settings
from app.core.registry import registry

log = structlog.get_logger(__name__)


async def _probe_unstructured_api() -> bool:
    if not settings.unstructured_api_url:
        return False
    try:
        headers = {}
        if settings.unstructured_api_key:
            headers["unstructured-api-key"] = settings.unstructured_api_key
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{settings.unstructured_api_url}/healthcheck",
                headers=headers,
            )
            log.info("unstructured_api_probe", status=r.status_code, url=settings.unstructured_api_url)
            return r.status_code == 200
    except Exception as e:
        log.error("unstructured_api_probe_failed", error=str(e), url=settings.unstructured_api_url)
        return False


async def _probe_local_unstructured() -> bool:
    if not settings.unstructured_local_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.unstructured_local_url}/healthcheck")
            return r.status_code == 200
    except Exception:
        return False


async def _probe_ollama() -> tuple[bool, int, str]:
    """Returns (reachable, dimension, model_name)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{settings.ollama_url}/api/embed",
                json={"model": settings.ollama_embed_model, "input": ["probe"]},
            )
            if r.status_code == 200:
                data = r.json()
                embeddings = data.get("embeddings", [[]])
                if embeddings and len(embeddings[0]) > 0:
                    dim = len(embeddings[0])
                    return True, dim, settings.ollama_embed_model
    except Exception:
        pass
    return False, 0, ""


def _probe_sentence_transformers() -> tuple[int, str]:
    """Loads ST model, returns (dimension, model_name). Blocks — run in executor."""
    from sentence_transformers import SentenceTransformer
    import torch

    torch.manual_seed(42)
    model = SentenceTransformer(settings.st_model, device="cpu")
    dim = model.get_sentence_embedding_dimension()
    return dim, settings.st_model


def _qdrant_url_with_port(url: str) -> str:
    """qdrant_client defaults to port 6333 when no port in URL. Force explicit port."""
    from urllib.parse import urlparse, urlunparse
    p = urlparse(url)
    if not p.port:
        port = 443 if p.scheme == "https" else 80
        netloc = f"{p.hostname}:{port}"
        return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
    return url


async def _probe_qdrant(embed_dim: int) -> bool:
    if not settings.qdrant_url:
        return False
    try:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.models import Distance, VectorParams

        client = AsyncQdrantClient(
            url=_qdrant_url_with_port(settings.qdrant_url),
            api_key=settings.qdrant_api_key or None,
            timeout=15.0,
            prefer_grpc=False,
        )
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]
        if settings.qdrant_collection not in existing:
            await client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),
                on_disk_payload=True,
            )
            log.info("qdrant_collection_created", name=settings.qdrant_collection)
        await client.close()
        return True
    except Exception as e:
        log.error("qdrant_probe_failed", error=str(e), error_type=type(e).__name__, url=settings.qdrant_url)
        return False


def _init_chroma(embed_dim: int) -> None:
    import chromadb
    import os

    os.makedirs(settings.chroma_persist_dir, exist_ok=True)
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    existing = [c.name for c in client.list_collections()]
    if settings.qdrant_collection not in existing:
        client.create_collection(
            name=settings.qdrant_collection,
            metadata={"hnsw:space": "cosine", "dimension": embed_dim},
        )
        log.info("chroma_collection_created", name=settings.qdrant_collection)


async def run_startup_probes() -> None:
    """
    Called once at application startup.
    Probes all external services, populates registry, freezes it.
    Any subsequent import of `registry` sees the frozen state.
    """
    log.info("startup_probes_begin")

    # ── 1. Parse backend ─────────────────────────────────────────────────────
    if await _probe_unstructured_api():
        registry.parse_backend = "unstructured_api"
        log.info("parse_backend", selected="unstructured_api")
    elif await _probe_local_unstructured():
        registry.parse_backend = "local_unstructured"
        log.info("parse_backend", selected="local_unstructured")
    else:
        registry.parse_backend = "local_parsers"
        log.info("parse_backend", selected="local_parsers")

    # ── 2. Embed backend (blocking probe runs in executor) ────────────────────
    loop = asyncio.get_event_loop()
    ollama_ok, ollama_dim, ollama_model = await _probe_ollama()
    if ollama_ok:
        registry.embed_backend = "ollama"
        registry.embed_dimension = ollama_dim
        registry.embed_model_name = ollama_model
        log.info("embed_backend", selected="ollama", dim=ollama_dim, model=ollama_model)
    else:
        log.info("ollama_unreachable_loading_sentence_transformers")
        dim, model_name = await loop.run_in_executor(
            None, _probe_sentence_transformers
        )
        registry.embed_backend = "sentence_transformers"
        registry.embed_dimension = dim
        registry.embed_model_name = model_name
        log.info("embed_backend", selected="sentence_transformers", dim=dim, model=model_name)

    # ── 3. Vector backend ─────────────────────────────────────────────────────
    if await _probe_qdrant(registry.embed_dimension):
        registry.vector_backend = "qdrant"
        log.info("vector_backend", selected="qdrant")
    else:
        await loop.run_in_executor(None, _init_chroma, registry.embed_dimension)
        registry.vector_backend = "chroma"
        log.info("vector_backend", selected="chroma_fallback")

    # ── 4. Search mode (derived) ──────────────────────────────────────────────
    if registry.vector_backend in ("qdrant", "chroma"):
        registry.search_mode = "hybrid"
    else:
        registry.search_mode = "fts_only"

    # ── 5. FREEZE ────────────────────────────────────────────────────────────
    registry.freeze()
    log.info("registry_frozen", **registry.as_dict())

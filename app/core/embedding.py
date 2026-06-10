import hashlib
import math
import re
from collections import Counter
from functools import lru_cache

import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)
_model = None
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def load_embedding_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("embedding_model_loading", model=settings.embed_model, device=device)
        _model = SentenceTransformer(
            settings.embed_model,
            device=device,
            cache_folder=str(settings.hf_home),
            token=settings.hf_token or None,
        )
        log.info("embedding_model_ready", model=settings.embed_model, device=device)
    return _model


def get_embedding(text: str) -> list[float]:
    return get_embeddings_batch([text], batch_size=1)[0]


def get_embeddings_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if not texts:
        return []
    vectors = load_embedding_model().encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    result = vectors.tolist()
    if result and len(result[0]) != settings.embed_dimension:
        raise RuntimeError(
            f"{settings.embed_model} returned {len(result[0])} dimensions; "
            f"configured dimension is {settings.embed_dimension}"
        )
    return result


@lru_cache(maxsize=65536)
def _token_id(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big")


def get_sparse_embedding(text: str) -> dict[int, float]:
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return {}
    counts = Counter(tokens)
    norm = math.sqrt(sum((1.0 + math.log(count)) ** 2 for count in counts.values()))
    return {_token_id(token): (1.0 + math.log(count)) / norm for token, count in counts.items()}

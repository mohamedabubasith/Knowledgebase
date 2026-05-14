"""
Frozen service registry — decided ONCE at startup, never changes at runtime.
Embedding dimension is locked here. Vector backend is locked here.
No runtime switching. Restart required for any change.
"""
from dataclasses import dataclass, field
from typing import Literal


ParseBackend = Literal["unstructured_api", "local_unstructured", "local_parsers"]
EmbedBackend = Literal["ollama", "sentence_transformers"]
VectorBackend = Literal["qdrant", "chroma"]
SearchMode = Literal["hybrid", "vector_only", "fts_only"]


@dataclass
class ServiceRegistry:
    # Parse
    parse_backend: ParseBackend = "local_parsers"

    # Embed — dimension locked at startup from live model probe
    embed_backend: EmbedBackend = "sentence_transformers"
    embed_dimension: int = 384
    embed_model_name: str = "all-MiniLM-L6-v2"

    # Vector
    vector_backend: VectorBackend = "chroma"

    # Search — derived from vector backend
    search_mode: SearchMode = "fts_only"

    # Frozen flag — set True after startup probes complete
    _frozen: bool = field(default=False, repr=False)

    def freeze(self) -> None:
        self._frozen = True

    def is_frozen(self) -> bool:
        return self._frozen

    def as_dict(self) -> dict:
        return {
            "parse_backend": self.parse_backend,
            "embed_backend": self.embed_backend,
            "embed_dimension": self.embed_dimension,
            "embed_model_name": self.embed_model_name,
            "vector_backend": self.vector_backend,
            "search_mode": self.search_mode,
        }


# Module-level singleton — imported everywhere
registry = ServiceRegistry()

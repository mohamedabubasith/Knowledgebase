"""
Vector store singleton — initialized at startup based on frozen registry.
Import `vector_store` everywhere; never instantiate backends directly.
"""
from app.core.registry import registry
from app.vectorstore.backend import VectorStoreBackend

_vector_store: VectorStoreBackend | None = None


def init_vector_store() -> None:
    global _vector_store
    assert registry.is_frozen()

    if registry.vector_backend == "qdrant":
        from app.vectorstore.qdrant_store import QdrantStore
        _vector_store = QdrantStore()
    else:
        from app.vectorstore.chroma_store import ChromaStore
        _vector_store = ChromaStore()


def get_vector_store() -> VectorStoreBackend:
    if _vector_store is None:
        raise RuntimeError("Vector store not initialized")
    return _vector_store

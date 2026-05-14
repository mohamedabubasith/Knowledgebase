"""
Abstract vector store interface.
Concrete backends: QdrantStore, ChromaStore.
Selected at startup, never swapped at runtime.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class VectorPoint:
    point_id: str          # = chunk_id (UUID string)
    vector: list[float]
    payload: dict          # tenant_id, document_id, chunk_index, etc.


@dataclass
class VectorHit:
    point_id: str
    score: float
    payload: dict


class VectorStoreBackend(ABC):

    @abstractmethod
    async def upsert_batch(self, points: list[VectorPoint]) -> None: ...

    @abstractmethod
    async def search(
        self,
        vector: list[float],
        tenant_id: str,
        top_k: int,
        document_id: Optional[str] = None,
    ) -> list[VectorHit]: ...

    @abstractmethod
    async def delete_by_document(self, document_id: str, tenant_id: str) -> None: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

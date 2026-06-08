from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Chunk, Document


class DocumentRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_kb(self, kb_id: UUID) -> list[Document]:
        return list((await self.db.scalars(
            select(Document).where(Document.knowledge_base_id == kb_id)
            .order_by(Document.created_at.desc())
        )).all())

    async def get_by_id(self, doc_id: UUID, kb_id: UUID) -> Document | None:
        return await self.db.scalar(
            select(Document).where(Document.id == doc_id, Document.knowledge_base_id == kb_id)
        )

    async def get_by_filename(self, kb_id: UUID, filename: str) -> Document | None:
        return await self.db.scalar(
            select(Document).where(Document.knowledge_base_id == kb_id, Document.filename == filename)
        )

    async def create(self, **fields) -> Document:
        doc = Document(**fields)
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def update_status(self, doc: Document, status: str, stage: str, error: str | None = None) -> None:
        doc.status = status
        doc.processing_stage = stage
        doc.error_message = error
        await self.db.flush()
        await self.db.refresh(doc)

    async def delete(self, doc: Document) -> None:
        await self.db.delete(doc)
        await self.db.flush()

    async def batch_status(self, doc_ids: list[UUID]) -> dict[str, dict]:
        if not doc_ids:
            return {}
        docs = (await self.db.scalars(
            select(Document).where(Document.id.in_(doc_ids))
        )).all()
        return {
            str(d.id): {
                "status": d.status,
                "processing_stage": d.processing_stage,
                "error_message": d.error_message,
            }
            for d in docs
        }

    async def list_chunks(self, doc_id: UUID) -> list[Chunk]:
        return list((await self.db.scalars(
            select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
        )).all())

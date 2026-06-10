from datetime import datetime
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Document, JobLog, KnowledgeBase


class JobLogRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: UUID) -> JobLog | None:
        return await self.db.get(JobLog, id)

    async def list_filtered(
        self,
        page: int = 1,
        page_size: int = 25,
        status: str | None = None,
        document_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        job_type: str | None = None,
    ) -> tuple[list[JobLog], int]:
        stmt = select(JobLog)
        if status:
            stmt = stmt.where(JobLog.status == status)
        if document_id:
            stmt = stmt.where(JobLog.document_id == document_id)
        if date_from:
            stmt = stmt.where(JobLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(JobLog.created_at <= date_to)
        if job_type:
            stmt = stmt.where(JobLog.job_type == job_type)
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items = list((await self.db.scalars(
            stmt.order_by(JobLog.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).all())
        return items, total

    async def enrich(self, items: list[JobLog]) -> list[dict]:
        doc_ids = [i.document_id for i in items if i.document_id]
        documents: dict = {x.id: x for x in (await self.db.scalars(
            select(Document).where(Document.id.in_(doc_ids))
        )).all()} if doc_ids else {}
        kb_ids = [doc.knowledge_base_id for doc in documents.values()]
        kbs: dict = {x.id: x.name for x in (await self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        )).all()} if kb_ids else {}
        result = []
        for item in items:
            doc = documents.get(item.document_id) if item.document_id else None
            result.append({
                "id": str(item.id),
                "job_id": item.job_id,
                "job_type": item.job_type,
                "document_id": str(item.document_id) if item.document_id else None,
                "document_name": doc.original_filename if doc else None,
                "knowledge_base_name": kbs.get(doc.knowledge_base_id) if doc else None,
                "status": item.status,
                "attempt": item.attempt,
                "duration_ms": item.duration_ms,
                "error_message": item.error_message,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            })
        return result

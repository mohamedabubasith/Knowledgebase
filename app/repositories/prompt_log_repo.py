from datetime import datetime
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import KnowledgeBase, PromptLog, User


class PromptLogRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **fields) -> PromptLog:
        log = PromptLog(**fields)
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def get_by_id(self, id: UUID) -> PromptLog | None:
        return await self.db.get(PromptLog, id)

    async def delete(self, log: PromptLog) -> None:
        await self.db.delete(log)
        await self.db.flush()

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[PromptLog]:
        return list((await self.db.scalars(
            select(PromptLog).where(PromptLog.user_id == user_id)
            .order_by(PromptLog.created_at.desc()).limit(limit)
        )).all())

    async def list_filtered(
        self,
        page: int = 1,
        page_size: int = 25,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        kb_id: UUID | None = None,
        user_id: UUID | None = None,
        search_type: str | None = None,
        min_score: float | None = None,
    ) -> tuple[list[PromptLog], int, dict, dict]:
        stmt = select(PromptLog)
        if status:
            stmt = stmt.where(PromptLog.status == status)
        if date_from:
            stmt = stmt.where(PromptLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(PromptLog.created_at <= date_to)
        if kb_id:
            stmt = stmt.where(PromptLog.knowledge_base_id == kb_id)
        if user_id:
            stmt = stmt.where(PromptLog.user_id == user_id)
        if search_type:
            stmt = stmt.where(PromptLog.search_type == search_type)
        if min_score is not None:
            stmt = stmt.where(PromptLog.similarity_threshold >= min_score)

        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items = list((await self.db.scalars(
            stmt.order_by(PromptLog.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).all())

        user_ids = [i.user_id for i in items if i.user_id]
        kb_ids = [i.knowledge_base_id for i in items if i.knowledge_base_id]
        users: dict = {x.id: x.email for x in (await self.db.scalars(
            select(User).where(User.id.in_(user_ids))
        )).all()} if user_ids else {}
        kbs: dict = {x.id: x.name for x in (await self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        )).all()} if kb_ids else {}

        return items, total, users, kbs

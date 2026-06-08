from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Chunk, Document, KBShare, KnowledgeBase, PromptLog, ShareRole, User


class KBRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[KnowledgeBase]:
        return list((await self.db.scalars(
            select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
        )).all())

    async def list_owned(self, owner_id: UUID) -> list[KnowledgeBase]:
        return list((await self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.owner_id == owner_id)
            .order_by(KnowledgeBase.created_at.desc())
        )).all())

    async def list_shared_ids(self, user_id: UUID) -> list[UUID]:
        return list((await self.db.scalars(
            select(KBShare.knowledge_base_id).where(KBShare.granted_to == user_id)
        )).all())

    async def list_by_ids(self, ids: list[UUID]) -> list[KnowledgeBase]:
        if not ids:
            return []
        return list((await self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.id.in_(ids))
            .order_by(KnowledgeBase.created_at.desc())
        )).all())

    async def get_by_id(self, id: UUID) -> KnowledgeBase | None:
        return await self.db.get(KnowledgeBase, id)

    async def create(self, name: str, description: str | None, owner_id: UUID, is_public: bool = False, settings: dict | None = None) -> KnowledgeBase:
        kb = KnowledgeBase(name=name, description=description, owner_id=owner_id, is_public=is_public, settings=settings or {})
        self.db.add(kb)
        await self.db.flush()
        await self.db.refresh(kb)
        return kb

    async def update(self, kb: KnowledgeBase, fields: dict) -> KnowledgeBase:
        for k, v in fields.items():
            setattr(kb, k, v)
        await self.db.flush()
        await self.db.refresh(kb)
        return kb

    async def delete(self, kb: KnowledgeBase) -> None:
        await self.db.delete(kb)
        await self.db.flush()

    async def get_share(self, kb_id: UUID, user_id: UUID) -> KBShare | None:
        return await self.db.scalar(
            select(KBShare).where(KBShare.knowledge_base_id == kb_id, KBShare.granted_to == user_id)
        )

    async def list_shares(self, kb_id: UUID) -> list[KBShare]:
        return list((await self.db.scalars(
            select(KBShare).where(KBShare.knowledge_base_id == kb_id)
        )).all())

    async def create_share(self, kb_id: UUID, grantee_id: UUID, granter_id: UUID, role: ShareRole) -> KBShare:
        share = KBShare(knowledge_base_id=kb_id, granted_to=grantee_id, granted_by=granter_id, role=role)
        self.db.add(share)
        await self.db.flush()
        await self.db.refresh(share)
        return share

    async def update_share(self, share: KBShare, role: ShareRole) -> None:
        share.role = role
        await self.db.flush()

    async def delete_share(self, share: KBShare) -> None:
        await self.db.delete(share)
        await self.db.flush()

    async def count_documents(self, kb_id: UUID) -> int:
        return await self.db.scalar(
            select(func.count()).select_from(Document).where(Document.knowledge_base_id == kb_id)
        ) or 0

    async def count_chunks(self, kb_id: UUID) -> int:
        return await self.db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.knowledge_base_id == kb_id)
        ) or 0

    async def count_prompts(self, kb_id: UUID) -> int:
        return await self.db.scalar(
            select(func.count()).select_from(PromptLog).where(PromptLog.knowledge_base_id == kb_id)
        ) or 0

    async def get_user_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    async def get_user_by_id(self, id: UUID) -> User | None:
        return await self.db.get(User, id)

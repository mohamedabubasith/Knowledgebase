from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Chunk, Document, KnowledgeBase, PromptLog, Tenant, User


class TenantRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Tenant]:
        return list((await self.db.scalars(select(Tenant).order_by(Tenant.created_at.desc()))).all())

    async def get_by_id(self, id: UUID) -> Tenant | None:
        return await self.db.get(Tenant, id)

    async def get_by_name(self, name: str) -> Tenant | None:
        return await self.db.scalar(select(Tenant).where(Tenant.name == name))

    async def get_by_user_id(self, user_id: UUID) -> Tenant | None:
        return await self.db.scalar(select(Tenant).where(Tenant.user_id == user_id))

    async def create(
        self, name: str, description: str | None, api_key_hash: str, api_key_prefix: str, user_id: UUID
    ) -> Tenant:
        tenant = Tenant(
            name=name, description=description,
            api_key_hash=api_key_hash, api_key_prefix=api_key_prefix, user_id=user_id,
        )
        self.db.add(tenant)
        await self.db.flush()
        await self.db.refresh(tenant)
        return tenant

    async def update_key(self, tenant: Tenant, api_key_hash: str, api_key_prefix: str) -> None:
        tenant.api_key_hash = api_key_hash
        tenant.api_key_prefix = api_key_prefix
        await self.db.flush()
        await self.db.refresh(tenant)

    async def set_active(self, tenant: Tenant, active: bool) -> None:
        tenant.is_active = active
        await self.db.flush()
        await self.db.refresh(tenant)

    async def get_kb_ids(self, user_id: UUID) -> list[UUID]:
        return list((await self.db.scalars(
            select(KnowledgeBase.id).where(KnowledgeBase.owner_id == user_id)
        )).all())

    async def get_doc_paths(self, kb_ids: list[UUID]) -> list[str]:
        if not kb_ids:
            return []
        docs = (await self.db.scalars(
            select(Document).where(Document.knowledge_base_id.in_(kb_ids))
        )).all()
        return [doc.file_path for doc in docs]

    async def delete_user_cascade(self, user_id: UUID) -> None:
        _ = await self.db.execute(sql_delete(User).where(User.id == user_id))

    async def get_stats(self, tenant: Tenant) -> dict:
        kb_ids = await self.get_kb_ids(tenant.user_id)
        today = datetime.now(timezone.utc).date()
        doc_count = await self.db.scalar(
            select(func.count()).select_from(Document).where(Document.knowledge_base_id.in_(kb_ids))
        ) if kb_ids else 0
        chunk_count = await self.db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.knowledge_base_id.in_(kb_ids))
        ) if kb_ids else 0
        prompts_today = await self.db.scalar(
            select(func.count()).select_from(PromptLog).where(
                PromptLog.user_id == tenant.user_id,
                func.date(PromptLog.created_at) == today,
            )
        )
        return {
            "knowledge_bases": len(kb_ids),
            "documents": doc_count or 0,
            "chunks": chunk_count or 0,
            "prompts_today": prompts_today or 0,
        }

    async def get_kbs_detail(self, user_id: UUID) -> list[dict]:
        kbs = (await self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.owner_id == user_id)
            .order_by(KnowledgeBase.created_at.desc())
        )).all()
        result = []
        for kb in kbs:
            doc_count = await self.db.scalar(
                select(func.count()).select_from(Document).where(Document.knowledge_base_id == kb.id)
            )
            chunk_count = await self.db.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.knowledge_base_id == kb.id)
            )
            result.append({
                "id": str(kb.id), "name": kb.name, "description": kb.description,
                "is_public": kb.is_public, "created_at": kb.created_at.isoformat(),
                "documents": doc_count or 0, "chunks": chunk_count or 0,
            })
        return result

    async def get_documents_detail(self, user_id: UUID, limit: int = 50) -> list[dict]:
        kb_ids = await self.get_kb_ids(user_id)
        if not kb_ids:
            return []
        docs = (await self.db.scalars(
            select(Document).where(Document.knowledge_base_id.in_(kb_ids))
            .order_by(Document.created_at.desc()).limit(limit)
        )).all()
        kb_map = {kb.id: kb.name for kb in (await self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        )).all()}
        return [
            {
                "id": str(d.id), "filename": d.filename, "file_type": d.file_type,
                "file_size": d.file_size, "status": d.status, "processing_stage": d.processing_stage,
                "knowledge_base_id": str(d.knowledge_base_id),
                "knowledge_base_name": kb_map.get(d.knowledge_base_id, "—"),
                "created_at": d.created_at.isoformat(),
            }
            for d in docs
        ]

    async def get_users_detail(self, tenant: Tenant) -> dict:
        from app.models.kb_share import KBShare
        system_user = await self.db.get(User, tenant.user_id)
        kb_ids = await self.get_kb_ids(tenant.user_id)
        shared_users = []
        if kb_ids:
            shares = (await self.db.scalars(
                select(KBShare).where(KBShare.knowledge_base_id.in_(kb_ids))
            )).all()
            seen: set[UUID] = set()
            for s in shares:
                if s.granted_to in seen:
                    continue
                seen.add(s.granted_to)
                u = await self.db.get(User, s.granted_to)
                kb = await self.db.get(KnowledgeBase, s.knowledge_base_id)
                if u:
                    shared_users.append({
                        "id": str(u.id), "email": u.email, "full_name": u.full_name,
                        "role": s.role, "kb_name": kb.name if kb else "—", "type": "shared",
                    })
        return {
            "system_user": {
                "id": str(system_user.id) if system_user else None,
                "email": system_user.email if system_user else None,
                "type": "system",
            },
            "shared_users": shared_users,
        }

    async def batch_status_docs(self, kb_ids: list[UUID], doc_ids: list[UUID]) -> dict[str, dict]:
        if not doc_ids or not kb_ids:
            return {}
        docs = (await self.db.scalars(
            select(Document).where(
                Document.id.in_(doc_ids),
                Document.knowledge_base_id.in_(kb_ids),
            )
        )).all()
        return {
            str(d.id): {
                "status": d.status,
                "processing_stage": d.processing_stage,
                "error_message": d.error_message,
            }
            for d in docs
        }

    async def get_prompt_logs_detail(self, tenant: Tenant, limit: int = 20) -> list[dict]:
        logs = (await self.db.scalars(
            select(PromptLog).where(PromptLog.user_id == tenant.user_id)
            .order_by(PromptLog.created_at.desc()).limit(limit)
        )).all()
        return [
            {
                "id": str(l.id), "prompt": l.prompt, "status": l.status,
                "latency_ms": l.latency_ms, "tokens_used": l.tokens_used,
                "search_type": l.search_type, "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ]

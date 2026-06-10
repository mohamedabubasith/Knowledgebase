from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import KnowledgeBase, ShareRole, User, UserRole
from app.repositories.kb_repo import KBRepo
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseStats, KnowledgeBaseUpdate

_ROLE_RANK = {"read": 0, "write": 1, "delete": 2}


class ShareRead:
    pass


class KBService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.kbs = KBRepo(db)

    def _is_admin(self, user: User) -> bool:
        return user.role in (UserRole.admin, UserRole.super_admin)

    async def _get_with_access(
        self, id: UUID, user: User, min_role: ShareRole | None = None
    ) -> KnowledgeBase:
        kb = await self.kbs.get_by_id(id)
        if not kb:
            raise HTTPException(404, "Knowledge base not found")
        if self._is_admin(user) or kb.owner_id == user.id:
            return kb
        share = await self.kbs.get_share(id, user.id)
        if not share:
            raise HTTPException(404, "Knowledge base not found")
        if min_role and _ROLE_RANK.get(share.role, 0) < _ROLE_RANK.get(min_role, 0):
            raise HTTPException(403, f"Requires {min_role} access on this knowledge base")
        return kb

    async def list_kbs(self, user: User) -> list[KnowledgeBase]:
        if self._is_admin(user):
            return await self.kbs.list_all()
        owned = await self.kbs.list_owned(user.id)
        shared_ids = await self.kbs.list_shared_ids(user.id)
        shared = await self.kbs.list_by_ids(shared_ids)
        seen = {kb.id for kb in owned}
        return owned + [kb for kb in shared if kb.id not in seen]

    async def create(self, body: KnowledgeBaseCreate, owner_id: UUID) -> KnowledgeBase:
        kb = await self.kbs.create(**body.model_dump(), owner_id=owner_id)
        await self.db.commit()
        return kb

    async def get(self, id: UUID, user: User, min_role: ShareRole | None = None) -> KnowledgeBase:
        return await self._get_with_access(id, user, min_role)

    async def update(self, id: UUID, body: KnowledgeBaseUpdate, user: User) -> KnowledgeBase:
        kb = await self._get_with_access(id, user, ShareRole.write)
        updated = await self.kbs.update(kb, body.model_dump(exclude_unset=True))
        await self.db.commit()
        return updated

    async def delete(self, id: UUID, user: User) -> str:
        kb = await self._get_with_access(id, user, ShareRole.delete)
        await self.kbs.delete(kb)
        await self.db.commit()
        return str(id)

    async def get_stats(self, id: UUID, user: User) -> KnowledgeBaseStats:
        await self._get_with_access(id, user)
        return KnowledgeBaseStats(
            documents=await self.kbs.count_documents(id),
            chunks=await self.kbs.count_chunks(id),
            prompts=await self.kbs.count_prompts(id),
        )

    async def list_shares(self, id: UUID, user: User) -> list[dict]:
        await self._get_with_access(id, user)
        shares = await self.kbs.list_shares(id)
        result = []
        for s in shares:
            grantee = await self.kbs.get_user_by_id(s.granted_to)
            result.append({
                "id": s.id,
                "knowledge_base_id": s.knowledge_base_id,
                "granted_to": s.granted_to,
                "grantee_email": grantee.email if grantee else "unknown",
                "grantee_name": grantee.full_name if grantee else None,
                "role": s.role,
            })
        return result

    async def share(self, id: UUID, user: User, email: str, role: ShareRole) -> dict:
        kb = await self._get_with_access(id, user)
        if kb.owner_id != user.id and not self._is_admin(user):
            raise HTTPException(403, "Only the owner can share this knowledge base")
        grantee = await self.kbs.get_user_by_email(email)
        if not grantee:
            raise HTTPException(404, f"No user found with email {email!r}")
        if grantee.id == kb.owner_id:
            raise HTTPException(400, "Cannot share with the owner")
        existing = await self.kbs.get_share(id, grantee.id)
        if existing:
            await self.kbs.update_share(existing, role)
            share = existing
        else:
            share = await self.kbs.create_share(id, grantee.id, user.id, role)
        await self.db.commit()
        return {
            "id": share.id,
            "knowledge_base_id": share.knowledge_base_id,
            "granted_to": share.granted_to,
            "grantee_email": grantee.email,
            "grantee_name": grantee.full_name,
            "role": share.role,
        }

    async def update_share(self, id: UUID, user: User, user_id: UUID, role: ShareRole) -> dict:
        kb = await self._get_with_access(id, user)
        if kb.owner_id != user.id and not self._is_admin(user):
            raise HTTPException(403, "Only the owner can update shares")
        share = await self.kbs.get_share(id, user_id)
        if not share:
            raise HTTPException(404, "Share not found")
        await self.kbs.update_share(share, role)
        await self.db.commit()
        grantee = await self.kbs.get_user_by_id(user_id)
        return {
            "id": share.id,
            "knowledge_base_id": share.knowledge_base_id,
            "granted_to": share.granted_to,
            "grantee_email": grantee.email if grantee else "unknown",
            "grantee_name": grantee.full_name if grantee else None,
            "role": share.role,
        }

    async def revoke_share(self, id: UUID, user: User, user_id: UUID) -> None:
        kb = await self._get_with_access(id, user)
        if kb.owner_id != user.id and not self._is_admin(user):
            raise HTTPException(403, "Only the owner can revoke shares")
        share = await self.kbs.get_share(id, user_id)
        if not share:
            raise HTTPException(404, "Share not found")
        await self.kbs.delete_share(share)
        await self.db.commit()

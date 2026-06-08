import hashlib
import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.minio import delete_file
from app.core.qdrant import delete_collection
from app.core.security import hash_password
from app.models import Tenant, UserRole
from app.repositories.tenant_repo import TenantRepo
from app.repositories.user_repo import UserRepo


def _generate_api_key() -> tuple[str, str, str]:
    raw = "kb_" + secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:12]
    return raw, hashed, prefix


class TenantCreated:
    def __init__(self, id, name, description, api_key_prefix, is_active, api_key):
        self.id = id
        self.name = name
        self.description = description
        self.api_key_prefix = api_key_prefix
        self.is_active = is_active
        self.api_key = api_key


class TenantService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.tenants = TenantRepo(db)
        self.users = UserRepo(db)

    async def list_tenants(self) -> list[Tenant]:
        return await self.tenants.list_all()

    async def get(self, id: UUID) -> Tenant:
        tenant = await self.tenants.get_by_id(id)
        if not tenant:
            raise HTTPException(404, "Tenant not found")
        return tenant

    async def create(self, name: str, description: str | None) -> dict:
        if await self.tenants.get_by_name(name):
            raise HTTPException(409, "Tenant name already exists")
        slug = name.lower().replace(" ", "-")
        email = f"tenant-{slug}@kb-system.app"
        if await self.users.get_by_email(email):
            raise HTTPException(409, "Tenant system user already exists")
        user = await self.users.create(
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name=name,
            role=UserRole.user,
        )
        raw_key, key_hash, prefix = _generate_api_key()
        tenant = await self.tenants.create(
            name=name, description=description,
            api_key_hash=key_hash, api_key_prefix=prefix, user_id=user.id,
        )
        await self.db.commit()
        return {
            "id": tenant.id, "name": tenant.name, "description": tenant.description,
            "api_key_prefix": prefix, "is_active": tenant.is_active, "api_key": raw_key,
        }

    async def rotate_key(self, id: UUID) -> dict:
        tenant = await self.get(id)
        raw_key, key_hash, prefix = _generate_api_key()
        await self.tenants.update_key(tenant, key_hash, prefix)
        await self.db.commit()
        return {
            "id": tenant.id, "name": tenant.name, "description": tenant.description,
            "api_key_prefix": prefix, "is_active": tenant.is_active, "api_key": raw_key,
        }

    async def set_active(self, id: UUID, active: bool) -> Tenant:
        tenant = await self.get(id)
        await self.tenants.set_active(tenant, active)
        await self.db.commit()
        return tenant

    async def delete(self, id: UUID) -> None:
        tenant = await self.get(id)
        kb_ids = await self.tenants.get_kb_ids(tenant.user_id)
        doc_paths = await self.tenants.get_doc_paths(kb_ids)
        for path in doc_paths:
            try:
                await delete_file(path)
            except Exception:
                pass
        for kb_id in kb_ids:
            try:
                await delete_collection(str(kb_id))
            except Exception:
                pass
        await self.tenants.delete_user_cascade(tenant.user_id)
        await self.db.commit()

    async def get_stats(self, id: UUID) -> dict:
        tenant = await self.get(id)
        return await self.tenants.get_stats(tenant)

    async def get_kbs(self, id: UUID) -> list[dict]:
        tenant = await self.get(id)
        return await self.tenants.get_kbs_detail(tenant.user_id)

    async def get_documents(self, id: UUID, limit: int = 50) -> list[dict]:
        tenant = await self.get(id)
        return await self.tenants.get_documents_detail(tenant.user_id, limit)

    async def get_users(self, id: UUID) -> dict:
        tenant = await self.get(id)
        return await self.tenants.get_users_detail(tenant)

    async def get_prompt_logs(self, id: UUID, limit: int = 20) -> list[dict]:
        tenant = await self.get(id)
        return await self.tenants.get_prompt_logs_detail(tenant, limit)

    async def batch_doc_status(self, id: UUID, doc_ids: list[UUID]) -> dict[str, dict]:
        tenant = await self.get(id)
        kb_ids = await self.tenants.get_kb_ids(tenant.user_id)
        return await self.tenants.batch_status_docs(kb_ids, doc_ids)

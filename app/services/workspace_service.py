import hashlib
import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repositories.kb_repo import KBRepo
from app.repositories.tenant_repo import TenantRepo
from app.repositories.user_repo import UserRepo


def _make_api_key() -> tuple[str, str, str]:
    raw = "kb_" + secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:12]
    return raw, hashed, prefix


class WorkspaceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.tenants = TenantRepo(db)
        self.users = UserRepo(db)
        self.kbs = KBRepo(db)

    async def _require_tenant(self, user: User):
        tenant = await self.tenants.get_by_user_id(user.id)
        if not tenant:
            raise HTTPException(404, "No workspace found for this user")
        return tenant

    async def get_me(self, user: User) -> dict:
        tenant = await self._require_tenant(user)
        stats = await self.tenants.get_stats(tenant)
        return {
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            },
            "workspace": {
                "id": str(tenant.id),
                "name": tenant.name,
                "description": tenant.description,
                "api_key_prefix": tenant.api_key_prefix,
                "is_active": tenant.is_active,
            },
            "stats": stats,
        }

    async def rotate_api_key(self, user: User) -> dict:
        tenant = await self._require_tenant(user)
        raw_key, key_hash, prefix = _make_api_key()
        await self.tenants.update_key(tenant, key_hash, prefix)
        await self.db.commit()
        return {
            "api_key": raw_key,
            "api_key_prefix": prefix,
        }

    async def list_members(self, user: User) -> list[dict]:
        tenant = await self._require_tenant(user)
        data = await self.tenants.get_users_detail(tenant)
        return data.get("shared_users", [])

    async def invite_member(self, user: User, email: str, kb_id: UUID, role: str) -> dict:
        from app.core.config import settings
        tenant = await self._require_tenant(user)

        # verify KB belongs to this tenant
        kb = await self.kbs.get_by_id(kb_id)
        if not kb or kb.owner_id != tenant.user_id:
            raise HTTPException(404, "Knowledge base not found in your workspace")

        # check if user already exists
        invitee = await self.users.get_by_email(email)

        if invitee:
            # user exists → create share directly
            existing = await self.kbs.get_share(kb_id, invitee.id)
            if existing:
                raise HTTPException(409, "User already has access to this KB")
            share = await self.kbs.create_share(kb_id, invitee.id, role)
            await self.db.commit()
            result = {"status": "added", "email": email, "role": role}
        else:
            result = {"status": "invited", "email": email, "role": role}

        # call n8n invite webhook
        if settings.n8n_invite_webhook:
            import httpx
            invite_url = f"{settings.app_base_url}/signup?invite_email={email}&kb={str(kb_id)}"
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    await client.post(settings.n8n_invite_webhook, json={
                        "email": email,
                        "inviter_name": user.full_name or user.email,
                        "workspace_name": tenant.name,
                        "kb_name": kb.name,
                        "role": role,
                        "invite_url": invite_url,
                    })
            except Exception:
                pass

        return result

    async def update_workspace(self, user: User, name: str | None, description: str | None) -> dict:
        tenant = await self._require_tenant(user)
        if name and name != tenant.name:
            if await self.tenants.get_by_name(name):
                raise HTTPException(409, "Workspace name already taken")
            tenant.name = name
        if description is not None:
            tenant.description = description
        await self.db.flush()
        await self.db.commit()
        return {
            "id": str(tenant.id),
            "name": tenant.name,
            "description": tenant.description,
            "api_key_prefix": tenant.api_key_prefix,
        }

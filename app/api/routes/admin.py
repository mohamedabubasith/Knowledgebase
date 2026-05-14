import hashlib
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from app.api.deps import AuthContext, require_admin
from app.db.models import ApiKey, Tenant
from app.db.session import get_session_factory

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateTenantRequest(BaseModel):
    name: str


class CreateKeyRequest(BaseModel):
    label: str
    role: str = "editor"
    tenant_id: str | None = None


class KeyResponse(BaseModel):
    key_id: str
    raw_key: str
    label: str
    role: str
    tenant_id: str


@router.post("/tenants")
async def create_tenant(
    req: CreateTenantRequest,
    auth: Annotated[AuthContext, Depends(require_admin)],
) -> dict:
    tenant = Tenant(id=str(uuid.uuid4()), name=req.name)
    factory = get_session_factory()
    async with factory() as session:
        session.add(tenant)
        await session.commit()
    return {"tenant_id": tenant.id, "name": tenant.name}


@router.post("/api-keys", response_model=KeyResponse)
async def create_api_key(
    req: CreateKeyRequest,
    auth: Annotated[AuthContext, Depends(require_admin)],
) -> KeyResponse:
    if req.role not in ("admin", "editor", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")

    target_tenant = req.tenant_id or auth.tenant_id
    raw_key = f"cortex_{secrets.token_urlsafe(32)}"
    key = ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=target_tenant,
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        label=req.label,
        role=req.role,
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(key)
        await session.commit()

    return KeyResponse(key_id=key.id, raw_key=raw_key, label=key.label, role=key.role, tenant_id=target_tenant)


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    auth: Annotated[AuthContext, Depends(require_admin)],
) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id, ApiKey.tenant_id == auth.tenant_id)
            .values(is_active=False)
        )
        await session.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked", "key_id": key_id}


@router.get("/api-keys")
async def list_api_keys(
    auth: Annotated[AuthContext, Depends(require_admin)],
) -> list[dict]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(
            select(ApiKey).where(ApiKey.tenant_id == auth.tenant_id).order_by(ApiKey.created_at.desc())
        )).scalars().all()

    return [
        {"id": r.id, "label": r.label, "role": r.role,
         "is_active": r.is_active, "last_used": r.last_used, "created_at": r.created_at}
        for r in rows
    ]

from uuid import UUID
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import require_super_admin
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/admin/tenants", tags=["tenants"], dependencies=[Depends(require_super_admin)])


class TenantCreate(BaseModel):
    name: str
    description: str | None = None


@router.get("")
async def list_tenants(db: AsyncSession = Depends(get_db)):
    return await TenantService(db).list_tenants()


@router.post("", status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).create(body.name, body.description)


@router.get("/{id}")
async def get_tenant(id: UUID, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).get(id)


@router.get("/{id}/knowledge-bases")
async def tenant_kbs(id: UUID, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).get_kbs(id)


@router.get("/{id}/documents")
async def tenant_documents(id: UUID, limit: int = 50, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).get_documents(id, limit)


@router.get("/{id}/documents/status")
async def tenant_documents_status(
    id: UUID,
    ids: list[UUID] = Query(...),
    db: AsyncSession = Depends(get_db),
):
    return await TenantService(db).batch_doc_status(id, ids)


@router.get("/{id}/users")
async def tenant_users(id: UUID, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).get_users(id)


@router.get("/{id}/prompt-logs")
async def tenant_prompt_logs(id: UUID, limit: int = 20, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).get_prompt_logs(id, limit)


@router.get("/{id}/stats")
async def tenant_stats(id: UUID, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).get_stats(id)


@router.post("/{id}/rotate")
async def rotate_key(id: UUID, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).rotate_key(id)


@router.patch("/{id}/deactivate")
async def deactivate(id: UUID, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).set_active(id, False)


@router.patch("/{id}/activate")
async def activate(id: UUID, db: AsyncSession = Depends(get_db)):
    return await TenantService(db).set_active(id, True)


@router.delete("/{id}", status_code=204)
async def delete_tenant(id: UUID, db: AsyncSession = Depends(get_db)):
    await TenantService(db).delete(id)

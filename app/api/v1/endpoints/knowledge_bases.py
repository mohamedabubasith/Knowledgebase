from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.qdrant import create_collection, delete_collection
from app.models import ShareRole, User
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseRead, KnowledgeBaseStats, KnowledgeBaseUpdate
from app.services.kb_service import KBService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


class ShareCreate(BaseModel):
    email: str
    role: ShareRole = ShareRole.read


class ShareUpdate(BaseModel):
    role: ShareRole


class ShareRead(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    granted_to: UUID
    grantee_email: str
    grantee_name: str | None = None
    role: ShareRole

    model_config = {"from_attributes": True}


@router.get("", response_model=list[KnowledgeBaseRead])
async def list_kbs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await KBService(db).list_kbs(user)


@router.post("", response_model=KnowledgeBaseRead, status_code=201)
async def create_kb(body: KnowledgeBaseCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    kb = await KBService(db).create(body, user.id)
    await create_collection(str(kb.id))
    return kb


@router.get("/{id}", response_model=KnowledgeBaseRead)
async def read_kb(id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await KBService(db).get(id, user)


@router.put("/{id}", response_model=KnowledgeBaseRead)
async def update_kb(id: UUID, body: KnowledgeBaseUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await KBService(db).update(id, body, user)


@router.delete("/{id}", status_code=204)
async def delete_kb(id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    kb_id = await KBService(db).delete(id, user)
    await delete_collection(kb_id)


@router.get("/{id}/stats", response_model=KnowledgeBaseStats)
async def kb_stats(id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await KBService(db).get_stats(id, user)


@router.get("/{id}/shares", response_model=list[ShareRead])
async def list_shares(id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await KBService(db).list_shares(id, user)


@router.post("/{id}/shares", response_model=ShareRead, status_code=201)
async def share_kb(id: UUID, body: ShareCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await KBService(db).share(id, user, body.email, body.role)


@router.put("/{id}/shares/{user_id}", response_model=ShareRead)
async def update_share(id: UUID, user_id: UUID, body: ShareUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await KBService(db).update_share(id, user, user_id, body.role)


@router.delete("/{id}/shares/{user_id}", status_code=204)
async def revoke_share(id: UUID, user_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await KBService(db).revoke_share(id, user, user_id)

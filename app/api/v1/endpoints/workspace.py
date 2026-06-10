from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspace", tags=["workspace"])


class InviteRequest(BaseModel):
    email: EmailStr
    kb_id: UUID
    role: str = "read"


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("/me")
async def get_me(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await WorkspaceService(db).get_me(user)


@router.post("/api-key/rotate")
async def rotate_api_key(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await WorkspaceService(db).rotate_api_key(user)


@router.get("/members")
async def list_members(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await WorkspaceService(db).list_members(user)


@router.post("/invite")
async def invite_member(body: InviteRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await WorkspaceService(db).invite_member(user, body.email, body.kb_id, body.role)


@router.patch("/settings")
async def update_workspace(body: WorkspaceUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await WorkspaceService(db).update_workspace(user, body.name, body.description)

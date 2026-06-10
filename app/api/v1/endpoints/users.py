from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import require_super_admin
from app.models import UserRole
from app.schemas.user import RoleUpdate, UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_super_admin)])


@router.get("", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db)):
    return await UserService(db).list_users()


@router.post("", response_model=UserRead, status_code=201)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    return await UserService(db).create(body)


@router.get("/{id}", response_model=UserRead)
async def get_user(id: UUID, db: AsyncSession = Depends(get_db)):
    return await UserService(db).get(id)


@router.put("/{id}", response_model=UserRead)
async def update_user(id: UUID, body: UserUpdate, db: AsyncSession = Depends(get_db)):
    return await UserService(db).update(id, body)


@router.patch("/{id}/role", response_model=UserRead)
async def update_role(id: UUID, body: RoleUpdate, db: AsyncSession = Depends(get_db)):
    return await UserService(db).set_role(id, body.role)


@router.delete("/{id}", status_code=204)
async def delete_user(id: UUID, db: AsyncSession = Depends(get_db)):
    await UserService(db).delete(id)

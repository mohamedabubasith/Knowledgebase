from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import require_super_admin
from app.core.security import hash_password
from app.models import User,UserRole
from app.schemas.user import UserCreate,UserRead,UserUpdate,RoleUpdate
router=APIRouter(prefix="/users",tags=["users"],dependencies=[Depends(require_super_admin)])
@router.get("",response_model=list[UserRead])
async def list_users(db:AsyncSession=Depends(get_db)):return (await db.scalars(select(User).order_by(User.created_at.desc()))).all()
@router.post("",response_model=UserRead,status_code=201)
async def create_user(body:UserCreate,db:AsyncSession=Depends(get_db)):
 if (await db.scalar(select(User).where(User.email==body.email))):raise HTTPException(409,"Email already exists")
 user=User(email=body.email,full_name=body.full_name,role=body.role,hashed_password=hash_password(body.password));db.add(user);await db.commit();await db.refresh(user);return user
async def get_or_404(id:UUID,db):
 user=await db.get(User,id)
 if not user:raise HTTPException(404,"User not found")
 return user
@router.get("/{id}",response_model=UserRead)
async def get_user(id:UUID,db:AsyncSession=Depends(get_db)):return await get_or_404(id,db)
@router.put("/{id}",response_model=UserRead)
async def update_user(id:UUID,body:UserUpdate,db:AsyncSession=Depends(get_db)):
 user=await get_or_404(id,db)
 for k,v in body.model_dump(exclude_unset=True).items():setattr(user,k,v)
 await db.commit();await db.refresh(user);return user
@router.patch("/{id}/role",response_model=UserRead)
async def role(id:UUID,body:RoleUpdate,db:AsyncSession=Depends(get_db)):
 user=await get_or_404(id,db);user.role=body.role;await db.commit();await db.refresh(user);return user
@router.delete("/{id}",status_code=204)
async def delete_user(id:UUID,db:AsyncSession=Depends(get_db)):
 user=await get_or_404(id,db)
 if user.role==UserRole.super_admin:raise HTTPException(400,"Super admins cannot be deleted")
 await db.delete(user);await db.commit()

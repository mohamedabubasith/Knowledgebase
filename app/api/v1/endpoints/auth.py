from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import create_access_token,create_refresh_token,decode_token,verify_password
from app.models import User
from app.schemas.user import LoginRequest,RefreshRequest,TokenPair,UserRead
router=APIRouter(prefix="/auth",tags=["auth"])
@router.post("/login",response_model=TokenPair)
async def login(body:LoginRequest,db:AsyncSession=Depends(get_db)):
 user=(await db.execute(select(User).where(User.email==body.email))).scalar_one_or_none()
 if not user or not user.is_active or not verify_password(body.password,user.hashed_password):raise HTTPException(401,"Invalid credentials")
 return TokenPair(access_token=create_access_token(str(user.id)),refresh_token=create_refresh_token(str(user.id)))
@router.post("/refresh",response_model=TokenPair)
async def refresh(body:RefreshRequest,db:AsyncSession=Depends(get_db)):
 try: payload=decode_token(body.refresh_token); assert payload.get("type")=="refresh"; user=await db.get(User,UUID(payload["sub"])); assert user and user.is_active
 except Exception: raise HTTPException(401,"Invalid refresh token")
 return TokenPair(access_token=create_access_token(str(user.id)),refresh_token=create_refresh_token(str(user.id)))
@router.get("/me",response_model=UserRead)
async def me(user:User=Depends(get_current_user)):return user

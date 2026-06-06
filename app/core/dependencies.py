from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole
oauth2_scheme=OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
async def get_current_user(token: str=Depends(oauth2_scheme), db: AsyncSession=Depends(get_db)) -> User:
    try: payload=decode_token(token); assert payload.get("type")=="access"; user=await db.get(User,UUID(payload["sub"]))
    except (JWTError,ValueError,AssertionError,KeyError): raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid credentials")
    if not user or not user.is_active: raise HTTPException(status_code=401,detail="Inactive or missing user")
    return user
async def require_super_admin(user: User=Depends(get_current_user))->User:
    if user.role!=UserRole.super_admin: raise HTTPException(status_code=403,detail="Super admin required")
    return user

import hashlib
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    # JWT auth
    if token:
        try:
            payload = decode_token(token)
            assert payload.get("type") == "access"
            user = await db.get(User, UUID(payload["sub"]))
        except (JWTError, ValueError, AssertionError, KeyError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Inactive or missing user")
        return user

    # API key auth
    if x_api_key:
        from app.models.tenant import Tenant
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        tenant = await db.scalar(
            select(Tenant).where(Tenant.api_key_hash == key_hash, Tenant.is_active == True)
        )
        if not tenant:
            raise HTTPException(status_code=401, detail="Invalid API key")
        user = await db.get(User, tenant.user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Tenant user inactive")
        return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Super admin required")
    return user

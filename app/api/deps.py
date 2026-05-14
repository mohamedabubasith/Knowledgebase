import hashlib
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey
from app.db.session import get_session_factory

_header = APIKeyHeader(name="X-Api-Key", auto_error=True)


class AuthContext:
    __slots__ = ("key_id", "tenant_id", "role")

    def __init__(self, key_id: str, tenant_id: str, role: str) -> None:
        self.key_id = key_id
        self.tenant_id = tenant_id
        self.role = role


async def get_auth(raw_key: Annotated[str, Security(_header)]) -> AuthContext:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    factory = get_session_factory()

    async with factory() as session:
        row = (await session.execute(
            select(ApiKey.id, ApiKey.tenant_id, ApiKey.role)
            .where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        )).one_or_none()

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    # update last_used without blocking response
    async with factory() as session:
        await session.execute(
            update(ApiKey).where(ApiKey.id == row.id).values(last_used=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
        )
        await session.commit()

    return AuthContext(key_id=str(row.id), tenant_id=str(row.tenant_id), role=row.role)


def require_editor(auth: Annotated[AuthContext, Depends(get_auth)]) -> AuthContext:
    if auth.role not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Editor role required")
    return auth


def require_admin(auth: Annotated[AuthContext, Depends(get_auth)]) -> AuthContext:
    if auth.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth

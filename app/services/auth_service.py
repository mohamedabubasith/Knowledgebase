import hashlib
import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.models import UserRole
from app.repositories.tenant_repo import TenantRepo
from app.repositories.user_repo import UserRepo
from app.schemas.user import SignupResponse, TokenPair

_RESET_TOKEN_TTL = 3600  # 1 hour


def _make_api_key() -> tuple[str, str, str]:
    raw = "kb_" + secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:12]
    return raw, hashed, prefix


async def _redis():
    import redis.asyncio as aioredis
    return await aioredis.from_url(settings.redis_url, decode_responses=True)


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepo(db)
        self.tenants = TenantRepo(db)

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self.users.get_by_email(email)
        if not user or not user.is_active or not verify_password(password, user.hashed_password):
            raise HTTPException(401, "Invalid credentials")
        return TokenPair(
            access_token=create_access_token(str(user.id)),
            refresh_token=create_refresh_token(str(user.id)),
        )

    async def refresh(self, refresh_token: str) -> TokenPair:
        try:
            payload = decode_token(refresh_token)
            assert payload.get("type") == "refresh"
            user = await self.users.get_by_id(UUID(payload["sub"]))
            assert user and user.is_active
        except Exception:
            raise HTTPException(401, "Invalid refresh token")
        return TokenPair(
            access_token=create_access_token(str(user.id)),
            refresh_token=create_refresh_token(str(user.id)),
        )

    async def signup(self, full_name: str, email: str, password: str, org_name: str) -> SignupResponse:
        if await self.users.get_by_email(email):
            raise HTTPException(409, "Email already registered")
        if await self.tenants.get_by_name(org_name):
            raise HTTPException(409, "Organisation name already taken")

        user = await self.users.create(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.user,
        )
        raw_key, key_hash, prefix = _make_api_key()
        tenant = await self.tenants.create(
            name=org_name,
            description=None,
            api_key_hash=key_hash,
            api_key_prefix=prefix,
            user_id=user.id,
        )
        await self.db.commit()

        return SignupResponse(
            access_token=create_access_token(str(user.id)),
            refresh_token=create_refresh_token(str(user.id)),
            api_key=raw_key,
            tenant_id=str(tenant.id),
            user_id=str(user.id),
        )

    async def forgot_password(self, email: str) -> None:
        user = await self.users.get_by_email(email)
        if not user:
            return  # silent — don't reveal whether email exists
        token = secrets.token_urlsafe(32)
        r = await _redis()
        try:
            await r.setex(f"pwd_reset:{token}", _RESET_TOKEN_TTL, str(user.id))
        finally:
            await r.aclose()
        if settings.n8n_password_reset_webhook:
            import httpx
            reset_url = f"{settings.app_base_url}/reset-password?token={token}"
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    await client.post(settings.n8n_password_reset_webhook, json={
                        "email": user.email,
                        "name": user.full_name or user.email,
                        "reset_url": reset_url,
                    })
            except Exception:
                pass  # best-effort

    async def reset_password(self, token: str, new_password: str) -> None:
        r = await _redis()
        try:
            user_id = await r.get(f"pwd_reset:{token}")
            if not user_id:
                raise HTTPException(400, "Invalid or expired reset token")
            await r.delete(f"pwd_reset:{token}")
        finally:
            await r.aclose()
        user = await self.users.get_by_id(UUID(user_id))
        if not user:
            raise HTTPException(400, "User not found")
        await self.users.update(user, {"hashed_password": hash_password(new_password)})
        await self.db.commit()

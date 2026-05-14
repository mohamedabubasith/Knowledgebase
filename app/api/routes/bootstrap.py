import hashlib
import secrets
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.models import ApiKey, Tenant
from app.db.session import get_session_factory

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])


class BootstrapResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    api_key: str
    message: str


@router.post("", response_model=BootstrapResponse)
async def bootstrap() -> BootstrapResponse:
    factory = get_session_factory()

    async with factory() as session:
        existing = (await session.execute(select(func.count()).select_from(ApiKey))).scalar()
        if existing > 0:
            raise HTTPException(status_code=409, detail="Already bootstrapped. Use existing admin key.")

        tenant = Tenant(id=str(uuid.uuid4()), name="Default")
        raw_key = f"cortex_{secrets.token_urlsafe(32)}"
        key = ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            label="admin-key",
            role="admin",
        )
        session.add(tenant)
        session.add(key)
        await session.commit()

    return BootstrapResponse(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        api_key=raw_key,
        message="Bootstrap complete. Save your API key — it will not be shown again.",
    )

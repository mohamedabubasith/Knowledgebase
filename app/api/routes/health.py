import asyncio
from fastapi import APIRouter
from sqlalchemy import text

from app.core.registry import registry
from app.db.session import get_session_factory
from app.models.schemas import ComponentHealth, HealthResponse
from app.vectorstore import get_vector_store

router = APIRouter(prefix="/health", tags=["health"])


async def _check_postgres() -> ComponentHealth:
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return ComponentHealth(status="ok")
    except Exception as e:
        return ComponentHealth(status="down", detail=str(e))


async def _check_vector_store() -> ComponentHealth:
    try:
        ok = await get_vector_store().health_check()
        return ComponentHealth(status="ok" if ok else "down")
    except Exception as e:
        return ComponentHealth(status="down", detail=str(e))


async def _check_minio() -> ComponentHealth:
    try:
        from app.core.config import settings
        from app.storage.minio_client import get_client
        get_client().bucket_exists(settings.minio_bucket_raw)
        return ComponentHealth(status="ok")
    except Exception as e:
        return ComponentHealth(status="down", detail=str(e))


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    pg, vs, minio = await asyncio.gather(
        _check_postgres(), _check_vector_store(), _check_minio()
    )
    components = {"postgres": pg, "vector_store": vs, "minio": minio}
    any_down = any(c.status == "down" for c in components.values())
    overall = "down" if pg.status == "down" else ("degraded" if any_down else "ok")
    return HealthResponse(status=overall, registry=registry.as_dict(), components=components)

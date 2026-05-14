"""
SQLAlchemy async engine + session factory.
Single engine instance shared across entire app.
"""
import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

log = structlog.get_logger(__name__)

_engine: AsyncEngine | None = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    global _engine, AsyncSessionLocal

    # asyncpg driver — replace scheme
    dsn = settings.postgres_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not dsn.startswith("postgresql+asyncpg://"):
        dsn = "postgresql+asyncpg://" + dsn.split("://", 1)[1]

    _engine = create_async_engine(
        dsn,
        pool_size=settings.postgres_pool_min,
        max_overflow=settings.postgres_pool_max - settings.postgres_pool_min,
        pool_pre_ping=True,
        echo=False,
        connect_args={"timeout": 30},  # 30s connect timeout for remote Postgres
    )
    AsyncSessionLocal = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    log.info("db_engine_ready", pool_size=settings.postgres_pool_min)


async def close_engine() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("DB engine not initialized")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if AsyncSessionLocal is None:
        raise RuntimeError("DB engine not initialized")
    return AsyncSessionLocal

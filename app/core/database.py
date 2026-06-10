from collections.abc import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

class Base(DeclarativeBase): pass
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session: yield session

async def init_db() -> None:
    import app.models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE documents ALTER COLUMN status TYPE VARCHAR(32) USING status::text"))
        await conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_stage VARCHAR(32) DEFAULT 'queued'"))
        await conn.execute(text("UPDATE documents SET status='queued', processing_stage='queued' WHERE status::text='pending'"))
        await conn.execute(text("UPDATE documents SET status='started', processing_stage='started' WHERE status::text='processing'"))
        await conn.execute(text("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding"))
        await conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS qdrant_point_id VARCHAR(255)"))
        await conn.execute(text("ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS top_k_used INTEGER"))
        await conn.execute(text("ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS similarity_threshold FLOAT"))
        await conn.execute(text("ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS total_sources_found INTEGER"))
        await conn.execute(text("ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS search_type VARCHAR(32) DEFAULT 'hybrid'"))

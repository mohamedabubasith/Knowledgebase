"""
Auto-migration: creates all tables + indexes + triggers at startup.
Uses SQLAlchemy metadata — no raw SQL for table definitions.
Only the Postgres-specific trigger DDL is raw (no ORM equivalent).
"""
import structlog
from sqlalchemy import Index, text

from app.db.models import Base, Chunk, Document
from app.db.session import get_engine

log = structlog.get_logger(__name__)

# Indexes not expressible in mapped_column (partial, GIN)
_EXTRA_INDEXES = [
    Index("idx_chunks_fts",       Chunk.fts_vector,  postgresql_using="gin"),
    Index("idx_chunks_vector_id", Chunk.vector_id,   postgresql_where=Chunk.vector_id.isnot(None)),
    Index("idx_apikeys_hash",     "api_keys",        "key_hash"),
    Index("idx_documents_status", Document.status),
    Index("idx_documents_checksum", Document.checksum),
    Index("idx_pstages_document", "pipeline_stages", "document_id"),
    Index("idx_audit_tenant_ts",  "audit_logs",      "tenant_id", "created_at"),
]


async def run_migrations() -> None:
    engine = get_engine()

    async with engine.begin() as conn:
        # Postgres extensions
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

        # Create all ORM-defined tables (IF NOT EXISTS behaviour built-in)
        await conn.run_sync(Base.metadata.create_all)

        # FTS auto-update trigger on chunks.chunk_text
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION set_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN NEW.updated_at = now(); RETURN NEW; END;
            $$ LANGUAGE plpgsql
        """))

        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'chunks_fts_update'
                ) THEN
                    CREATE TRIGGER chunks_fts_update
                        BEFORE INSERT OR UPDATE OF chunk_text ON chunks
                        FOR EACH ROW
                        EXECUTE FUNCTION
                            tsvector_update_trigger(fts_vector, 'pg_catalog.english', chunk_text);
                END IF;
            END $$
        """))

        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'documents_updated_at'
                ) THEN
                    CREATE TRIGGER documents_updated_at
                        BEFORE UPDATE ON documents
                        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
                END IF;
            END $$
        """))

    log.info("migrations_complete")

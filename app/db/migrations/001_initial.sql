-- Cortex KB — idempotent schema (safe to run every startup)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Tenants ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── API Keys ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash    TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('admin','editor','viewer')),
    is_active   BOOLEAN NOT NULL DEFAULT true,
    last_used   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_apikeys_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_apikeys_hash   ON api_keys(key_hash);

-- ── Documents ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    minio_path    TEXT NOT NULL,
    file_size     BIGINT,
    checksum      TEXT NOT NULL,
    parse_mode    TEXT,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                    'pending','parsing','chunked','embedding',
                    'embedded','indexed','parse_failed',
                    'embed_failed','error','deleting','deleted'
                  )),
    page_count    INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_tenant   ON documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_status   ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_checksum ON documents(checksum);

-- ── Chunks ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id    UUID NOT NULL,
    chunk_index  INT NOT NULL,
    chunk_text   TEXT NOT NULL,
    token_count  INT NOT NULL,
    page_number  INT,
    start_char   INT NOT NULL,
    end_char     INT NOT NULL,
    checksum     TEXT NOT NULL,
    vector_id    TEXT,
    fts_vector   TSVECTOR,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_tenant    ON chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document  ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_fts       ON chunks USING GIN(fts_vector);
CREATE INDEX IF NOT EXISTS idx_chunks_vector_id ON chunks(vector_id) WHERE vector_id IS NOT NULL;

-- FTS trigger (replace so re-running is safe)
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'chunks_fts_update'
    ) THEN
        CREATE TRIGGER chunks_fts_update
            BEFORE INSERT OR UPDATE OF chunk_text
            ON chunks
            FOR EACH ROW
            EXECUTE FUNCTION tsvector_update_trigger(fts_vector, 'pg_catalog.english', chunk_text);
    END IF;
END $$;

-- ── Pipeline Stages ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_stages (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id    UUID NOT NULL,
    stage        TEXT NOT NULL CHECK (stage IN ('upload','parse','chunk','embed','index')),
    status       TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','done','failed','skipped')),
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    detail       JSONB,
    UNIQUE (document_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_pstages_document ON pipeline_stages(document_id);
CREATE INDEX IF NOT EXISTS idx_pstages_tenant   ON pipeline_stages(tenant_id);

-- ── Audit Logs ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID NOT NULL,
    action        TEXT NOT NULL,
    resource_type TEXT,
    resource_id   UUID,
    metadata      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts ON audit_logs(tenant_id, created_at DESC);

-- updated_at trigger on documents
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'documents_updated_at'
    ) THEN
        CREATE TRIGGER documents_updated_at
            BEFORE UPDATE ON documents
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

"""
SQLAlchemy 2.0 ORM models — single source of truth for all tables.
All tables created via Base.metadata.create_all() at startup.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id:         Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name:       Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    api_keys:  Mapped[list["ApiKey"]]  = relationship(back_populates="tenant", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id:         Mapped[str]  = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id:  Mapped[str]  = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    key_hash:   Mapped[str]  = mapped_column(String, nullable=False, unique=True)
    label:      Mapped[str]  = mapped_column(String, nullable=False)
    role:       Mapped[str]  = mapped_column(String, nullable=False)
    is_active:  Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tenant: Mapped["Tenant"] = relationship(back_populates="api_keys")


class Document(Base):
    __tablename__ = "documents"

    id:         Mapped[str]  = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id:  Mapped[str]  = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    filename:   Mapped[str]  = mapped_column(String, nullable=False)
    mime_type:  Mapped[str]  = mapped_column(String, nullable=False)
    minio_path: Mapped[str]  = mapped_column(String, nullable=False)
    file_size:  Mapped[Optional[int]]  = mapped_column(BigInteger, nullable=True)
    checksum:   Mapped[str]  = mapped_column(String, nullable=False)
    parse_mode: Mapped[Optional[str]]  = mapped_column(String, nullable=True)
    status:     Mapped[str]  = mapped_column(String, nullable=False, default="pending")
    page_count: Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    tenant:          Mapped["Tenant"]          = relationship(back_populates="documents")
    chunks:          Mapped[list["Chunk"]]     = relationship(back_populates="document", cascade="all, delete-orphan")
    pipeline_stages: Mapped[list["PipelineStage"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id:          Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    tenant_id:   Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text:  Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    start_char:  Mapped[int] = mapped_column(Integer, nullable=False)
    end_char:    Mapped[int] = mapped_column(Integer, nullable=False)
    checksum:    Mapped[str] = mapped_column(String, nullable=False)
    vector_id:   Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fts_vector:  Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = (UniqueConstraint("document_id", "stage"),)

    id:           Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id:  Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    tenant_id:    Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    stage:        Mapped[str] = mapped_column(String, nullable=False)
    status:       Mapped[str] = mapped_column(String, nullable=False, default="pending")
    started_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    detail:       Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="pipeline_stages")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id:            Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id:     Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    action:        Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id:   Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True)
    metadata_:     Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PipelineJob(Base):
    """
    Durable job queue backed by PostgreSQL.
    Workers claim rows via SELECT FOR UPDATE SKIP LOCKED.
    Failed jobs are retried with exponential backoff (max_attempts).
    """
    __tablename__ = "pipeline_jobs"

    id:           Mapped[str]           = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id:  Mapped[str]           = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    tenant_id:    Mapped[str]           = mapped_column(UUID(as_uuid=False), nullable=False)
    stage:        Mapped[str]           = mapped_column(String, nullable=False)   # ingest|embed|index|purge
    status:       Mapped[str]           = mapped_column(String, nullable=False, default="pending")  # pending|processing|done|failed
    payload:      Mapped[dict]          = mapped_column(JSONB, nullable=False, default=dict)
    attempt:      Mapped[int]           = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int]           = mapped_column(Integer, nullable=False, default=3)
    last_error:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)
    locked_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)

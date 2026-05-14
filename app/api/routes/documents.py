from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update

from app.api.deps import AuthContext, get_auth, require_editor
from app.db.models import Chunk, Document
from app.db.session import get_session_factory
from app.models.schemas import ChunkOut, DocumentOut
from app.workers.queue import purge_queue

router = APIRouter(prefix="/documents", tags=["documents"])
log = structlog.get_logger(__name__)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    auth: Annotated[AuthContext, Depends(get_auth)],
    limit: int = 50,
    offset: int = 0,
) -> list[DocumentOut]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(
            select(Document)
            .where(Document.tenant_id == auth.tenant_id, Document.status != "deleted")
            .order_by(Document.created_at.desc())
            .limit(limit).offset(offset)
        )).scalars().all()
    return [DocumentOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    auth: Annotated[AuthContext, Depends(get_auth)],
) -> DocumentOut:
    factory = get_session_factory()
    async with factory() as session:
        row = (await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == auth.tenant_id,
                Document.status != "deleted",
            )
        )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut.model_validate(row, from_attributes=True)


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    document_id: str,
    auth: Annotated[AuthContext, Depends(get_auth)],
    limit: int = 100,
    offset: int = 0,
) -> list[ChunkOut]:
    factory = get_session_factory()
    async with factory() as session:
        doc = (await session.execute(
            select(Document.id).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
        )).scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        rows = (await session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id, Chunk.tenant_id == auth.tenant_id)
            .order_by(Chunk.chunk_index)
            .limit(limit).offset(offset)
        )).scalars().all()

    return [ChunkOut.model_validate(r, from_attributes=True) for r in rows]


@router.delete("/{document_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_document(
    document_id: str,
    auth: Annotated[AuthContext, Depends(require_editor)],
) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        row = (await session.execute(
            select(Document.id, Document.minio_path).where(
                Document.id == document_id,
                Document.tenant_id == auth.tenant_id,
                Document.status != "deleted",
            )
        )).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found")

        await session.execute(
            update(Document).where(Document.id == document_id).values(status="deleting")
        )
        await session.commit()

    await purge_queue.put({
        "document_id": document_id,
        "tenant_id": auth.tenant_id,
        "minio_path": row.minio_path,
    })
    return {"status": "deleting", "document_id": document_id}

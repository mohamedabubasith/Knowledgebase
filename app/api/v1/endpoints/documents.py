from uuid import UUID
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User
from app.schemas.document import ChunkRead, DocumentRead
from app.services.document_service import DocumentService

router = APIRouter(prefix="/knowledge-bases/{kb_id}/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRead])
async def list_documents(kb_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await DocumentService(db).list_docs(kb_id, user)


@router.post("/upload", response_model=DocumentRead, status_code=202)
async def upload(kb_id: UUID, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await DocumentService(db).upload(kb_id, user, file)


@router.get("/status")
async def batch_status(
    kb_id: UUID,
    ids: list[UUID] = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await DocumentService(db).batch_status(kb_id, user, ids)


@router.get("/{id}", response_model=DocumentRead)
async def read_document(kb_id: UUID, id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await DocumentService(db).get(kb_id, id, user)


@router.delete("/{id}", status_code=204)
async def delete_document(kb_id: UUID, id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await DocumentService(db).delete(kb_id, id, user)


@router.get("/{id}/download", response_class=RedirectResponse)
async def download(kb_id: UUID, id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return RedirectResponse(await DocumentService(db).download_url(kb_id, id, user))


@router.post("/{id}/reprocess", response_model=DocumentRead, status_code=202)
async def reprocess(kb_id: UUID, id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await DocumentService(db).reprocess(kb_id, id, user)


@router.get("/{id}/chunks", response_model=list[ChunkRead])
async def chunks(kb_id: UUID, id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await DocumentService(db).get_chunks(kb_id, id, user)

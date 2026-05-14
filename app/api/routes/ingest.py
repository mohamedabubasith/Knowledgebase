import hashlib
import uuid
from typing import Annotated

import filetype
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import AuthContext, require_editor
from app.core.pipeline import update_stage
from app.db.models import AuditLog, Document
from app.db.session import get_session_factory
from app.models.schemas import IngestResponse
from app.storage.minio_client import upload_file
from app.workers.queue import ingest_queue

router = APIRouter(prefix="/ingest", tags=["ingest"])
log = structlog.get_logger(__name__)

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/html",
    "application/xhtml+xml",
}

MAX_FILE_SIZE = 100 * 1024 * 1024


@router.post("/upload", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: Annotated[UploadFile, File()],
    auth: Annotated[AuthContext, Depends(require_editor)],
) -> IngestResponse:
    data = await file.read()

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 100MB limit")

    kind = filetype.guess(data[:2048])
    if kind is not None:
        detected_mime = kind.mime
    else:
        ct = (file.content_type or "").split(";")[0].strip().lower()
        detected_mime = ct if ct else "application/octet-stream"

    if detected_mime not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {detected_mime}")

    checksum = hashlib.sha256(data).hexdigest()
    document_id = str(uuid.uuid4())
    filename = file.filename or "upload"
    factory = get_session_factory()

    async with factory() as session:
        existing = (await session.execute(
            select(Document.id).where(
                Document.checksum == checksum,
                Document.tenant_id == auth.tenant_id,
                Document.status != "deleted",
            )
        )).scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=409, detail=f"Document already exists: {existing}")

        minio_path = await upload_file(auth.tenant_id, document_id, filename, data, detected_mime)

        doc = Document(
            id=document_id,
            tenant_id=auth.tenant_id,
            filename=filename,
            mime_type=detected_mime,
            minio_path=minio_path,
            file_size=len(data),
            checksum=checksum,
            status="pending",
        )
        session.add(doc)
        session.add(AuditLog(tenant_id=auth.tenant_id, action="upload", resource_type="document", resource_id=document_id))
        await session.commit()

    await update_stage(document_id, auth.tenant_id, "upload", "done", {
        "filename": filename, "mime_type": detected_mime,
        "file_size": len(data), "minio_path": minio_path,
    })
    await ingest_queue.put({
        "document_id": document_id, "tenant_id": auth.tenant_id,
        "filename": filename, "mime_type": detected_mime, "minio_path": minio_path,
    })

    log.info("upload_enqueued", document_id=document_id, size=len(data))
    return IngestResponse(document_id=document_id, status="pending", message="Ingestion queued")

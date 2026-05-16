import hashlib
import uuid
from typing import Annotated, Optional

import filetype
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import AuthContext, require_editor
from app.core.pipeline import update_stage
from app.db.models import AuditLog, Document
from app.db.session import get_session_factory
from app.models.schemas import IngestResponse
from app.storage.minio_client import upload_file
from app.workers.db_queue import enqueue

router = APIRouter(prefix="/ingest", tags=["ingest"])
log = structlog.get_logger(__name__)

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/msword",
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-excel",                                                  # .xls
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/html",
    "application/xhtml+xml",
    # Tabular — handled by DuckDB NL2SQL pipeline
    "text/csv",
    "text/tab-separated-values",
    "application/csv",
}

# .docx / .pptx / .xlsx are ZIP-based — filetype.guess() returns application/zip.
# CSV/TSV are plain text — filetype.guess() returns None → octet-stream.
# Map back to correct MIME by filename extension.
_ZIP_EXTENSION_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_EXT_MIME_FALLBACK = {
    ".csv":  "text/csv",
    ".tsv":  "text/tab-separated-values",
    ".xls":  "application/vnd.ms-excel",
}

MAX_FILE_SIZE = 100 * 1024 * 1024


@router.post("/upload", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: Annotated[UploadFile, File()],
    auth: Annotated[AuthContext, Depends(require_editor)],
    parsing_strategy: Annotated[Optional[str], Form()] = "fast",
) -> IngestResponse:
    data = await file.read()

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 100MB limit")

    # Prefer content-type sent by client if specific (cortex-ai sets it from extension).
    ct = (file.content_type or "").split(";")[0].strip().lower()
    if ct and ct not in ("application/octet-stream", ""):
        detected_mime = ct
    else:
        kind = filetype.guess(data[:2048])
        detected_mime = kind.mime if kind else "application/octet-stream"

    import os as _os
    ext = _os.path.splitext(file.filename or "")[1].lower()

    # filetype.guess() returns application/zip for Office Open XML (.docx/.pptx/.xlsx).
    if detected_mime == "application/zip":
        detected_mime = _ZIP_EXTENSION_MIME.get(ext, detected_mime)

    # filetype.guess() returns None (→ octet-stream) for plain-text formats like CSV/TSV.
    if detected_mime == "application/octet-stream" and ext in _EXT_MIME_FALLBACK:
        detected_mime = _EXT_MIME_FALLBACK[ext]

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
    strategy = parsing_strategy if parsing_strategy in ("fast", "hi_res") else "fast"
    await enqueue(
        stage="ingest",
        document_id=document_id,
        tenant_id=auth.tenant_id,
        payload={
            "document_id": document_id, "tenant_id": auth.tenant_id,
            "filename": filename, "mime_type": detected_mime, "minio_path": minio_path,
            "parsing_strategy": strategy,
        },
    )

    log.info("upload_enqueued", document_id=document_id, size=len(data))
    return IngestResponse(document_id=document_id, status="pending", message="Ingestion queued")

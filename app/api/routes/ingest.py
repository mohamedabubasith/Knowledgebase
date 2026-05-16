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

_FAILED_STATUSES = {"failed", "error", "parse_failed", "chunk_failed", "embed_failed", "index_failed"}
_TERMINAL_STATUSES = _FAILED_STATUSES | {"indexed"}


def _detect_mime(data: bytes, content_type: str, filename: str) -> str:
    """Resolve MIME from client hint → filetype magic → extension fallback."""
    import os as _os
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct and ct not in ("application/octet-stream", ""):
        detected = ct
    else:
        kind = filetype.guess(data[:2048])
        detected = kind.mime if kind else "application/octet-stream"

    ext = _os.path.splitext(filename)[1].lower()
    if detected == "application/zip":
        detected = _ZIP_EXTENSION_MIME.get(ext, detected)
    if detected == "application/octet-stream" and ext in _EXT_MIME_FALLBACK:
        detected = _EXT_MIME_FALLBACK[ext]
    return detected


@router.post("/upload", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: Annotated[UploadFile, File()],
    auth: Annotated[AuthContext, Depends(require_editor)],
    parsing_strategy: Annotated[Optional[str], Form()] = "fast",
) -> IngestResponse:
    data = await file.read()

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 100MB limit")

    filename     = file.filename or "upload"
    detected_mime = _detect_mime(data, file.content_type or "", filename)
    strategy     = parsing_strategy if parsing_strategy in ("fast", "hi_res", "ocr_only", "auto") else "fast"

    if detected_mime not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {detected_mime}")

    checksum = hashlib.sha256(data).hexdigest()
    factory  = get_session_factory()

    # ── Duplicate detection ───────────────────────────────────────────────────
    async with factory() as session:
        existing_doc = (await session.execute(
            select(Document).where(
                Document.checksum == checksum,
                Document.tenant_id == auth.tenant_id,
                Document.status != "deleted",
            )
        )).scalar_one_or_none()

    if existing_doc:
        doc_id = existing_doc.id

        if existing_doc.status == "indexed":
            # Already fully processed — return immediately, no pipeline needed.
            log.info("upload_duplicate_indexed", document_id=doc_id)
            return IngestResponse(
                document_id=doc_id,
                status="indexed",
                message="Document already indexed — no reprocessing needed",
            )

        if existing_doc.status in _FAILED_STATUSES:
            # Previous run failed — reprocess from stored MinIO file.
            log.info("upload_duplicate_failed_reprocessing", document_id=doc_id)
            existing_doc.status = "pending"
            async with factory() as session:
                from sqlalchemy import update as _update
                await session.execute(
                    _update(Document).where(Document.id == doc_id).values(status="pending")
                )
                await session.commit()

            await update_stage(doc_id, auth.tenant_id, "parse", "pending")
            await update_stage(doc_id, auth.tenant_id, "chunk", "pending")
            await update_stage(doc_id, auth.tenant_id, "embed", "pending")
            await update_stage(doc_id, auth.tenant_id, "index", "pending")
            await enqueue(
                stage="ingest",
                document_id=doc_id,
                tenant_id=auth.tenant_id,
                payload={
                    "document_id": doc_id, "tenant_id": auth.tenant_id,
                    "filename": existing_doc.filename, "mime_type": existing_doc.mime_type,
                    "minio_path": existing_doc.minio_path, "parsing_strategy": strategy,
                },
            )
            log.info("upload_duplicate_requeued", document_id=doc_id)
            return IngestResponse(
                document_id=doc_id,
                status="pending",
                message="Previous ingestion failed — reprocessing from stored file",
            )

        # Still in progress (pending/parsing/embedding/…) — return existing id.
        log.info("upload_duplicate_in_progress", document_id=doc_id, status=existing_doc.status)
        return IngestResponse(
            document_id=doc_id,
            status=existing_doc.status,
            message="Document is already being processed",
        )

    # ── New document ──────────────────────────────────────────────────────────
    document_id = str(uuid.uuid4())
    minio_path  = await upload_file(auth.tenant_id, document_id, filename, data, detected_mime)

    async with factory() as session:
        session.add(Document(
            id=document_id,
            tenant_id=auth.tenant_id,
            filename=filename,
            mime_type=detected_mime,
            minio_path=minio_path,
            file_size=len(data),
            checksum=checksum,
            status="pending",
        ))
        session.add(AuditLog(
            tenant_id=auth.tenant_id, action="upload",
            resource_type="document", resource_id=document_id,
        ))
        await session.commit()

    await update_stage(document_id, auth.tenant_id, "upload", "done", {
        "filename": filename, "mime_type": detected_mime,
        "file_size": len(data), "minio_path": minio_path,
    })
    await enqueue(
        stage="ingest",
        document_id=document_id,
        tenant_id=auth.tenant_id,
        payload={
            "document_id": document_id, "tenant_id": auth.tenant_id,
            "filename": filename, "mime_type": detected_mime,
            "minio_path": minio_path, "parsing_strategy": strategy,
        },
    )

    log.info("upload_enqueued", document_id=document_id, size=len(data))
    return IngestResponse(document_id=document_id, status="pending", message="Ingestion queued")


@router.post("/reprocess/{document_id}", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(
    document_id: str,
    auth: Annotated[AuthContext, Depends(require_editor)],
    parsing_strategy: Annotated[Optional[str], Form()] = "fast",
) -> IngestResponse:
    """
    Re-enqueue a failed (or stuck) document for ingestion.

    Resets pipeline stages and re-runs the full ingest → embed → index flow.
    Useful after transient errors (timeouts, OOM, connectivity issues).
    """
    factory = get_session_factory()
    async with factory() as session:
        doc = (await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == auth.tenant_id,
                Document.status != "deleted",
            )
        )).scalar_one_or_none()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Reset to pending so pipeline can re-run
        doc.status = "pending"
        await session.commit()

    strategy = parsing_strategy if parsing_strategy in ("fast", "hi_res", "ocr_only", "auto") else "fast"

    # Reset all pipeline stages
    await update_stage(document_id, auth.tenant_id, "parse", "pending")
    await update_stage(document_id, auth.tenant_id, "chunk", "pending")
    await update_stage(document_id, auth.tenant_id, "embed", "pending")
    await update_stage(document_id, auth.tenant_id, "index", "pending")

    await enqueue(
        stage="ingest",
        document_id=document_id,
        tenant_id=auth.tenant_id,
        payload={
            "document_id": document_id, "tenant_id": auth.tenant_id,
            "filename": doc.filename, "mime_type": doc.mime_type, "minio_path": doc.minio_path,
            "parsing_strategy": strategy,
        },
    )

    log.info("reprocess_enqueued", document_id=document_id, strategy=strategy)
    return IngestResponse(document_id=document_id, status="pending", message="Reprocessing queued")

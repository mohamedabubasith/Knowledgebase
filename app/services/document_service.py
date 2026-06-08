import mimetypes
import uuid
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.minio import delete_file, get_presigned_url, upload_file
from app.core.qdrant import delete_chunks_by_document
from app.models import Chunk, Document, DocumentStatus, ShareRole, User
from app.repositories.document_repo import DocumentRepo
from app.services.kb_service import KBService
from app.services.worker_operations import enqueue_document_job


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.docs = DocumentRepo(db)
        self.kb_svc = KBService(db)

    async def list_docs(self, kb_id: UUID, user: User) -> list[Document]:
        await self.kb_svc.get(kb_id, user)
        return await self.docs.list_by_kb(kb_id)

    async def upload(self, kb_id: UUID, user: User, file: UploadFile) -> Document:
        await self.kb_svc.get(kb_id, user, min_role=ShareRole.write)

        document_id = uuid.uuid4()
        original = file.filename or "upload"
        data = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(413, "File too large")

        content_type = file.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream"
        object_key = f"{kb_id}/{document_id}/{original}"

        existing = await self.docs.get_by_filename(kb_id, original)
        if existing:
            await delete_chunks_by_document(str(kb_id), str(existing.id))
            await self.docs.delete(existing)

        await upload_file(data, object_key, content_type)
        doc = await self.docs.create(
            id=document_id, knowledge_base_id=kb_id, filename=original, original_filename=original,
            file_type=content_type, file_size=len(data), file_path=object_key,
            status=DocumentStatus.queued, processing_stage="queued", metadata_={},
        )
        await self.db.commit()

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await enqueue_document_job(redis, doc.id)
        await redis.close()
        return doc

    async def get(self, kb_id: UUID, doc_id: UUID, user: User, min_role: ShareRole | None = None) -> Document:
        await self.kb_svc.get(kb_id, user, min_role=min_role)
        doc = await self.docs.get_by_id(doc_id, kb_id)
        if not doc:
            raise HTTPException(404, "Document not found")
        return doc

    async def delete(self, kb_id: UUID, doc_id: UUID, user: User) -> None:
        doc = await self.get(kb_id, doc_id, user, min_role=ShareRole.delete)
        path = doc.file_path
        await delete_chunks_by_document(str(kb_id), str(doc_id))
        await self.docs.delete(doc)
        await self.db.commit()
        await delete_file(path)

    async def download_url(self, kb_id: UUID, doc_id: UUID, user: User) -> str:
        doc = await self.get(kb_id, doc_id, user)
        return await get_presigned_url(doc.file_path)

    async def reprocess(self, kb_id: UUID, doc_id: UUID, user: User) -> Document:
        doc = await self.get(kb_id, doc_id, user, min_role=ShareRole.write)
        await self.docs.update_status(doc, DocumentStatus.queued, "queued", error=None)
        doc.error_message = None
        await self.db.commit()

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await enqueue_document_job(redis, doc.id)
        await redis.close()
        return doc

    async def get_chunks(self, kb_id: UUID, doc_id: UUID, user: User) -> list[Chunk]:
        await self.get(kb_id, doc_id, user)
        return await self.docs.list_chunks(doc_id)

    async def batch_status(self, kb_id: UUID, user: User, doc_ids: list[UUID]) -> dict[str, dict]:
        await self.kb_svc.get(kb_id, user)
        return await self.docs.batch_status(doc_ids)

from uuid import UUID
from arq.connections import RedisSettings
from sqlalchemy import delete
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Chunk,Document,DocumentStatus
from app.services.document_processor import parse_document,chunk_text
from app.services.embedding_service import embed_many
async def process_document(ctx,document_id:str):
    async with SessionLocal() as db:
        document=await db.get(Document,UUID(document_id))
        if not document:return
        document.status=DocumentStatus.processing; document.error_message=None; await db.commit()
        try:
            text=parse_document(document.file_path); parts=chunk_text(text); vectors=await embed_many(parts)
            await db.execute(delete(Chunk).where(Chunk.document_id==document.id))
            db.add_all([Chunk(document_id=document.id,knowledge_base_id=document.knowledge_base_id,content=part,embedding=vector,chunk_index=i,metadata_={"filename":document.original_filename}) for i,(part,vector) in enumerate(zip(parts,vectors))])
            document.status=DocumentStatus.completed;document.chunk_count=len(parts);await db.commit()
        except Exception as exc:
            await db.rollback(); document=await db.get(Document,UUID(document_id)); document.status=DocumentStatus.failed;document.error_message=str(exc)[:4000];await db.commit();raise
class WorkerSettings:
    functions=[process_document];redis_settings=RedisSettings.from_dsn(settings.redis_url);max_jobs=10;job_timeout=3600

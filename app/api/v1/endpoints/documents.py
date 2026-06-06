import mimetypes,os,uuid
from pathlib import Path
from uuid import UUID
import aiofiles
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter,Depends,File,HTTPException,UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import Chunk,Document,DocumentStatus,User
from app.schemas.document import ChunkRead,DocumentRead
from app.api.v1.endpoints.knowledge_bases import get_kb
router=APIRouter(prefix="/knowledge-bases/{kb_id}/documents",tags=["documents"])
async def get_doc(kb_id,id,db,user):
 await get_kb(kb_id,db,user);doc=await db.scalar(select(Document).where(Document.id==id,Document.knowledge_base_id==kb_id))
 if not doc:raise HTTPException(404,"Document not found")
 return doc
@router.get("",response_model=list[DocumentRead])
async def list_documents(kb_id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 await get_kb(kb_id,db,user);return (await db.scalars(select(Document).where(Document.knowledge_base_id==kb_id).order_by(Document.created_at.desc()))).all()
@router.post("/upload",response_model=DocumentRead,status_code=202)
async def upload(kb_id:UUID,file:UploadFile=File(...),db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 await get_kb(kb_id,db,user);settings.upload_dir.mkdir(parents=True,exist_ok=True);stored=f"{uuid.uuid4()}{Path(file.filename or 'upload').suffix.lower()}";path=settings.upload_dir/stored;size=0
 try:
  async with aiofiles.open(path,"wb") as out:
   while data:=await file.read(1024*1024):
    size+=len(data)
    if size>settings.max_upload_size_mb*1024*1024:raise HTTPException(413,"File too large")
    await out.write(data)
 except Exception: path.unlink(missing_ok=True);raise
 doc=Document(knowledge_base_id=kb_id,filename=stored,original_filename=file.filename or stored,file_type=file.content_type or mimetypes.guess_type(stored)[0] or "application/octet-stream",file_size=size,file_path=str(path),metadata_={});db.add(doc);await db.commit();await db.refresh(doc)
 redis=await create_pool(RedisSettings.from_dsn(settings.redis_url));await redis.enqueue_job("process_document",str(doc.id));await redis.close();return doc
@router.get("/{id}",response_model=DocumentRead)
async def read_document(kb_id:UUID,id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):return await get_doc(kb_id,id,db,user)
@router.delete("/{id}",status_code=204)
async def delete_document(kb_id:UUID,id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 doc=await get_doc(kb_id,id,db,user);path=doc.file_path;await db.delete(doc);await db.commit();Path(path).unlink(missing_ok=True)
@router.post("/{id}/reprocess",response_model=DocumentRead,status_code=202)
async def reprocess(kb_id:UUID,id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 doc=await get_doc(kb_id,id,db,user);doc.status=DocumentStatus.pending;doc.error_message=None;await db.commit();redis=await create_pool(RedisSettings.from_dsn(settings.redis_url));await redis.enqueue_job("process_document",str(doc.id));await redis.close();await db.refresh(doc);return doc
@router.get("/{id}/chunks",response_model=list[ChunkRead])
async def chunks(kb_id:UUID,id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 await get_doc(kb_id,id,db,user);return (await db.scalars(select(Chunk).where(Chunk.document_id==id).order_by(Chunk.chunk_index))).all()

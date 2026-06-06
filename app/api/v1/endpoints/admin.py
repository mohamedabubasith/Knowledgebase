from datetime import datetime,timezone
from uuid import UUID
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy import func,select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_super_admin
from app.core.ollama import ollama
from app.models import Chunk,Document,KnowledgeBase,PromptLog,User
from app.schemas.prompt_log import PromptLogRead
router=APIRouter(prefix="/admin",tags=["admin"],dependencies=[Depends(require_super_admin)])
@router.get("/stats")
async def stats(db:AsyncSession=Depends(get_db)):
 async def count(m):return await db.scalar(select(func.count()).select_from(m))
 today=datetime.now(timezone.utc).date();return {"knowledge_bases":await count(KnowledgeBase),"documents":await count(Document),"chunks":await count(Chunk),"users":await count(User),"prompts_today":await db.scalar(select(func.count()).select_from(PromptLog).where(func.date(PromptLog.created_at)==today))}
@router.get("/prompt-logs")
async def logs(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=200),status:str|None=None,db:AsyncSession=Depends(get_db)):
 stmt=select(PromptLog)
 if status:stmt=stmt.where(PromptLog.status==status)
 total=await db.scalar(select(func.count()).select_from(stmt.subquery()));items=(await db.scalars(stmt.order_by(PromptLog.created_at.desc()).offset((page-1)*page_size).limit(page_size))).all();return {"items":[PromptLogRead.model_validate(i) for i in items],"total":total,"page":page,"page_size":page_size}
@router.get("/prompt-logs/{id}",response_model=PromptLogRead)
async def log(id:UUID,db:AsyncSession=Depends(get_db)):
 item=await db.get(PromptLog,id)
 if not item:raise HTTPException(404,"Log not found")
 return item
@router.delete("/prompt-logs/{id}",status_code=204)
async def delete_log(id:UUID,db:AsyncSession=Depends(get_db)):
 item=await db.get(PromptLog,id)
 if not item:raise HTTPException(404,"Log not found")
 await db.delete(item);await db.commit()
@router.get("/queue-status")
async def queue_status():
 redis=await create_pool(RedisSettings.from_dsn(settings.redis_url));queued=await redis.zcard("arq:queue");info=await redis.info();await redis.close();return {"healthy":True,"queued":queued,"redis_version":info.get("redis_version")}
@router.get("/models")
async def models():return await ollama.models()
@router.post("/models/pull")
async def pull(model:str):return await ollama.pull(model)

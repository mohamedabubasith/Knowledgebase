from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import func,select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import Chunk,Document,KnowledgeBase,PromptLog,User,UserRole
from app.schemas.knowledge_base import KnowledgeBaseCreate,KnowledgeBaseRead,KnowledgeBaseStats,KnowledgeBaseUpdate
router=APIRouter(prefix="/knowledge-bases",tags=["knowledge-bases"])
def scope(user):return True if user.role in (UserRole.admin,UserRole.super_admin) else KnowledgeBase.owner_id==user.id
async def get_kb(id,db,user):
 kb=await db.scalar(select(KnowledgeBase).where(KnowledgeBase.id==id,scope(user)))
 if not kb:raise HTTPException(404,"Knowledge base not found")
 return kb
@router.get("",response_model=list[KnowledgeBaseRead])
async def list_kbs(db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):return (await db.scalars(select(KnowledgeBase).where(scope(user)).order_by(KnowledgeBase.created_at.desc()))).all()
@router.post("",response_model=KnowledgeBaseRead,status_code=201)
async def create_kb(body:KnowledgeBaseCreate,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 kb=KnowledgeBase(**body.model_dump(),owner_id=user.id);db.add(kb);await db.commit();await db.refresh(kb);return kb
@router.get("/{id}",response_model=KnowledgeBaseRead)
async def read_kb(id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):return await get_kb(id,db,user)
@router.put("/{id}",response_model=KnowledgeBaseRead)
async def update_kb(id:UUID,body:KnowledgeBaseUpdate,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 kb=await get_kb(id,db,user)
 for k,v in body.model_dump(exclude_unset=True).items():setattr(kb,k,v)
 await db.commit();await db.refresh(kb);return kb
@router.delete("/{id}",status_code=204)
async def delete_kb(id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 kb=await get_kb(id,db,user);await db.delete(kb);await db.commit()
@router.get("/{id}/stats",response_model=KnowledgeBaseStats)
async def stats(id:UUID,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 await get_kb(id,db,user)
 async def count(model):return await db.scalar(select(func.count()).select_from(model).where(model.knowledge_base_id==id))
 return KnowledgeBaseStats(documents=await count(Document),chunks=await count(Chunk),prompts=await count(PromptLog))

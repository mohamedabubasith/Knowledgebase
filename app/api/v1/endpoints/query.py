import json,time
from fastapi import APIRouter,Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import PromptLog,PromptStatus,User
from app.api.v1.endpoints.knowledge_bases import get_kb
from app.schemas.query import QueryRequest,QueryResponse,SearchResult
from app.services.llm_service import answer_question
from app.services.search_service import semantic_search
router=APIRouter(prefix="/query",tags=["query"])
@router.post("/search",response_model=list[SearchResult])
async def search(body:QueryRequest,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 await get_kb(body.knowledge_base_id,db,user);return await semantic_search(db,body.knowledge_base_id,body.prompt,body.top_k)
@router.post("",response_model=QueryResponse)
async def query(body:QueryRequest,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 start=time.perf_counter();sources=[]
 try:
  await get_kb(body.knowledge_base_id,db,user);sources=await semantic_search(db,body.knowledge_base_id,body.prompt,body.top_k);response,tokens=await answer_question(body.prompt,sources);latency=int((time.perf_counter()-start)*1000);log=PromptLog(user_id=user.id,knowledge_base_id=body.knowledge_base_id,prompt=body.prompt,response=response,sources=[{**s,"chunk_id":str(s["chunk_id"]),"document_id":str(s["document_id"])} for s in sources],tokens_used=tokens,latency_ms=latency,model_used=settings.llm_model,status=PromptStatus.success,metadata_={});db.add(log);await db.commit();return QueryResponse(response=response,sources=sources,tokens_used=tokens,latency_ms=latency,model_used=settings.llm_model)
 except Exception as exc:
  await db.rollback();db.add(PromptLog(user_id=user.id,knowledge_base_id=body.knowledge_base_id,prompt=body.prompt,response="",sources=[],latency_ms=int((time.perf_counter()-start)*1000),model_used=settings.llm_model,status=PromptStatus.failed,error=str(exc),metadata_={}));await db.commit();raise
@router.post("/stream")
async def stream(body:QueryRequest,db:AsyncSession=Depends(get_db),user:User=Depends(get_current_user)):
 result=await query(body,db,user)
 async def events():
  yield f"data: {json.dumps(result.model_dump(mode='json'))}\n\n";yield "data: [DONE]\n\n"
 return StreamingResponse(events(),media_type="text/event-stream")

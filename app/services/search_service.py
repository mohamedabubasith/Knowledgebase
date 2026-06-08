import asyncio
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embedding import get_embedding,get_sparse_embedding
from app.core.minio import get_presigned_url
from app.core.qdrant import count_above_threshold,hybrid_search as qdrant_hybrid_search


async def hybrid_search(db:AsyncSession,kb_id:UUID,query:str,top_k:int=5,score_threshold:float=0.3,search_type:str="hybrid")->tuple[list[dict],int]:
    query_dense,query_sparse=await asyncio.gather(asyncio.to_thread(get_embedding,query),asyncio.to_thread(get_sparse_embedding,query))
    results,total=await asyncio.gather(
        qdrant_hybrid_search(str(kb_id),query_dense,query_sparse,top_k,score_threshold,search_type=search_type),
        count_above_threshold(str(kb_id),query_dense,query_sparse,score_threshold,search_type),
    )
    sources=[]
    for rank,point in enumerate(results):
        payload=point.payload or {}
        sources.append({"chunk_id":point.id,"document_id":payload["document_id"],"document_name":payload.get("document_name",""),"knowledge_base_id":kb_id,"knowledge_base_name":payload.get("kb_name",""),"content":payload.get("content",""),"similarity_score":round(float(point.score),4),"relevance_score":round(1/(rank+1),4),"chunk_index":payload.get("chunk_index",0),"page_number":payload.get("page_number"),"presigned_url":await get_presigned_url(payload["object_key"]),"metadata":payload.get("metadata",{})})
    return sources,total


async def semantic_search(db:AsyncSession,kb_id:UUID,query:str,top_k:int=5)->list[dict]:
    sources,_=await hybrid_search(db,kb_id,query,top_k)
    return sources

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chunk import Chunk
from app.services.embedding_service import embed_text
async def semantic_search(db:AsyncSession,kb_id:UUID,query:str,top_k:int=5)->list[dict]:
    vector=await embed_text(query)
    distance=Chunk.embedding.cosine_distance(vector)
    rows=(await db.execute(select(Chunk,distance.label("distance")).where(Chunk.knowledge_base_id==kb_id).order_by(distance).limit(top_k))).all()
    return [{"chunk_id":c.id,"document_id":c.document_id,"content":c.content,"similarity":max(0.0,1-float(d)),"metadata":c.metadata_} for c,d in rows]

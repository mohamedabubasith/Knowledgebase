from uuid import UUID
from pydantic import BaseModel,Field
class QueryRequest(BaseModel): knowledge_base_id:UUID; prompt:str=Field(min_length=1); top_k:int=Field(default=5,ge=1,le=20)
class SearchResult(BaseModel): chunk_id:UUID; document_id:UUID; content:str; similarity:float; metadata:dict={}
class QueryResponse(BaseModel): response:str; sources:list[SearchResult]; tokens_used:int; latency_ms:int; model_used:str

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,Field
class QueryRequest(BaseModel): knowledge_base_id:UUID; prompt:str=Field(min_length=1); top_k:int=Field(default=5,ge=1,le=20); similarity_threshold:float=Field(default=0.3,ge=0,le=1); search_type:Literal["hybrid","dense","sparse"]="hybrid"; include_sources:bool=True
class SourceChunk(BaseModel): chunk_id:UUID; document_id:UUID; document_name:str; knowledge_base_id:UUID; knowledge_base_name:str=""; content:str; similarity_score:float; relevance_score:float; chunk_index:int; page_number:int|None=None; presigned_url:str; metadata:dict={}
SearchResult=SourceChunk
class QueryResponse(BaseModel): query_id:UUID; prompt:str; response:str; sources:list[SourceChunk]; total_sources_found:int; top_k_used:int; similarity_threshold:float; search_type:str; model_used:str; tokens_used:int; latency_ms:float; created_at:datetime

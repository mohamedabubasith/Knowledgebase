from uuid import UUID
from pydantic import Field
from app.models.prompt_log import PromptStatus
from app.schemas.common import Identified
class PromptLogRead(Identified): user_id:UUID|None; knowledge_base_id:UUID|None; user_email:str|None=None; knowledge_base_name:str|None=None; prompt:str; response:str; sources:list; tokens_used:int; latency_ms:int; model_used:str; status:PromptStatus; error:str|None; top_k_used:int|None; similarity_threshold:float|None; total_sources_found:int|None; search_type:str; metadata:dict=Field(validation_alias="metadata_")

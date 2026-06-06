from uuid import UUID
from pydantic import Field
from app.models.prompt_log import PromptStatus
from app.schemas.common import Identified
class PromptLogRead(Identified): user_id:UUID|None; knowledge_base_id:UUID|None; prompt:str; response:str; sources:list; tokens_used:int; latency_ms:int; model_used:str; status:PromptStatus; error:str|None; metadata:dict=Field(validation_alias="metadata_")

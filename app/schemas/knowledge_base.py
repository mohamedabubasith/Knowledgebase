from uuid import UUID
from pydantic import BaseModel,Field
from app.schemas.common import Identified
class KnowledgeBaseCreate(BaseModel): name:str=Field(min_length=1,max_length=255); description:str|None=None; is_public:bool=False; settings:dict={}
class KnowledgeBaseUpdate(BaseModel): name:str|None=None; description:str|None=None; is_public:bool|None=None; settings:dict|None=None
class KnowledgeBaseRead(Identified): name:str; description:str|None; owner_id:UUID; is_public:bool; settings:dict
class KnowledgeBaseStats(BaseModel): documents:int; chunks:int; prompts:int

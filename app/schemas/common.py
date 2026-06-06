from datetime import datetime
from uuid import UUID
from pydantic import BaseModel,ConfigDict
class ORMModel(BaseModel): model_config=ConfigDict(from_attributes=True)
class Message(BaseModel): message: str
class Page(BaseModel): items:list; total:int; page:int; page_size:int
class Identified(ORMModel): id:UUID; created_at:datetime; updated_at:datetime

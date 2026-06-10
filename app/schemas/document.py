from uuid import UUID
from pydantic import Field
from app.models.document import DocumentStatus
from app.schemas.common import Identified
class DocumentRead(Identified):
    knowledge_base_id:UUID; filename:str; original_filename:str; file_type:str; file_size:int; file_path:str; status:DocumentStatus; processing_stage:str; error_message:str|None; chunk_count:int; metadata:dict=Field(validation_alias="metadata_")
class ChunkRead(Identified): document_id:UUID; knowledge_base_id:UUID; content:str; chunk_index:int; qdrant_point_id:str|None; metadata:dict=Field(validation_alias="metadata_")

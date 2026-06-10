import enum,uuid
from sqlalchemy import ForeignKey,JSON,String,Text,BigInteger,Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.core.database import Base
from app.models.base import UUIDTimestampMixin
class DocumentStatus(str,enum.Enum):
    queued="queued"; started="started"; parsing="parsing"; chunking="chunking"; embedding="embedding"; indexing="indexing"; completed="completed"; failed="failed"
class Document(UUIDTimestampMixin,Base):
    __tablename__="documents"
    knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),index=True)
    filename: Mapped[str]=mapped_column(String(255)); original_filename: Mapped[str]=mapped_column(String(255)); file_type: Mapped[str]=mapped_column(String(100)); file_size: Mapped[int]=mapped_column(BigInteger); file_path: Mapped[str]=mapped_column(String(1024)); status: Mapped[DocumentStatus]=mapped_column(String(32),default=DocumentStatus.queued,index=True); processing_stage: Mapped[str]=mapped_column(String(32),default=DocumentStatus.queued.value,index=True); error_message: Mapped[str|None]=mapped_column(Text,nullable=True); chunk_count: Mapped[int]=mapped_column(Integer,default=0); metadata_: Mapped[dict]=mapped_column("metadata",JSON,default=dict)
    knowledge_base=relationship("KnowledgeBase",back_populates="documents"); chunks=relationship("Chunk",cascade="all, delete-orphan")

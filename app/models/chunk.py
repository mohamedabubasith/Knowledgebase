import uuid
from sqlalchemy import ForeignKey,JSON,Text,Integer,String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
from app.models.base import UUIDTimestampMixin
class Chunk(UUIDTimestampMixin,Base):
    __tablename__="chunks"
    document_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("documents.id",ondelete="CASCADE"),index=True); knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),index=True); content: Mapped[str]=mapped_column(Text); chunk_index: Mapped[int]=mapped_column(Integer); qdrant_point_id: Mapped[str|None]=mapped_column(String(255),nullable=True,index=True); metadata_: Mapped[dict]=mapped_column("metadata",JSON,default=dict)

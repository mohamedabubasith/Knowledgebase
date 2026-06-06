import uuid
from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey,JSON,Text,Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
from app.models.base import UUIDTimestampMixin
class Chunk(UUIDTimestampMixin,Base):
    __tablename__="chunks"
    document_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("documents.id",ondelete="CASCADE"),index=True); knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),index=True); content: Mapped[str]=mapped_column(Text); embedding: Mapped[list[float]]=mapped_column(Vector(768)); chunk_index: Mapped[int]=mapped_column(Integer); metadata_: Mapped[dict]=mapped_column("metadata",JSON,default=dict)

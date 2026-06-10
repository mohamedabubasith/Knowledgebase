import uuid
from sqlalchemy import Boolean, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.core.database import Base
from app.models.base import UUIDTimestampMixin
class KnowledgeBase(UUIDTimestampMixin,Base):
    __tablename__="knowledge_bases"
    name: Mapped[str]=mapped_column(String(255),index=True)
    description: Mapped[str|None]=mapped_column(Text,nullable=True)
    owner_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("users.id",ondelete="CASCADE"))
    is_public: Mapped[bool]=mapped_column(Boolean,default=False)
    settings: Mapped[dict]=mapped_column(JSON,default=dict)
    owner=relationship("User",back_populates="knowledge_bases")
    documents=relationship("Document",back_populates="knowledge_base",cascade="all, delete-orphan")

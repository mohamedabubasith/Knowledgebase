import enum,uuid
from sqlalchemy import Enum,ForeignKey,JSON,Text,Integer,String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
from app.models.base import UUIDTimestampMixin
class PromptStatus(str,enum.Enum): success="success"; failed="failed"
class PromptLog(UUIDTimestampMixin,Base):
    __tablename__="prompt_logs"
    user_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("users.id",ondelete="SET NULL"),nullable=True,index=True); knowledge_base_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="SET NULL"),nullable=True,index=True); prompt: Mapped[str]=mapped_column(Text); response: Mapped[str]=mapped_column(Text,default=""); sources: Mapped[list]=mapped_column(JSON,default=list); tokens_used: Mapped[int]=mapped_column(Integer,default=0); latency_ms: Mapped[int]=mapped_column(Integer,default=0); model_used: Mapped[str]=mapped_column(String(255)); status: Mapped[PromptStatus]=mapped_column(Enum(PromptStatus)); error: Mapped[str|None]=mapped_column(Text,nullable=True); metadata_: Mapped[dict]=mapped_column("metadata",JSON,default=dict)

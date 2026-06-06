import enum
from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import UUIDTimestampMixin
class UserRole(str,enum.Enum): super_admin="super_admin"; admin="admin"; user="user"
class User(UUIDTimestampMixin,Base):
    __tablename__="users"
    email: Mapped[str]=mapped_column(String(320),unique=True,index=True)
    hashed_password: Mapped[str]=mapped_column(String(255))
    full_name: Mapped[str]=mapped_column(String(255),default="")
    role: Mapped[UserRole]=mapped_column(Enum(UserRole),default=UserRole.user)
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)
    knowledge_bases=relationship("KnowledgeBase",back_populates="owner")

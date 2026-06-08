import enum
import uuid

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDTimestampMixin


class ShareRole(str, enum.Enum):
    read = "read"
    write = "write"
    delete = "delete"


_ROLE_RANK = {"read": 0, "write": 1, "delete": 2}


def role_gte(actual: "ShareRole", required: "ShareRole") -> bool:
    return _ROLE_RANK.get(actual, 0) >= _ROLE_RANK.get(required, 0)


class KBShare(UUIDTimestampMixin, Base):
    __tablename__ = "kb_shares"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "granted_to", name="uq_kb_share"),)

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    granted_to: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[ShareRole] = mapped_column(Enum(ShareRole), default=ShareRole.read)

    grantee = relationship("User", foreign_keys=[granted_to])
    granter = relationship("User", foreign_keys=[granted_by])

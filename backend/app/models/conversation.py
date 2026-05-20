import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, ForeignKey, DateTime, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.message import Message


class ConversationStatus(str, enum.Enum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ARCHIVED = "archived"


class Conversation(BaseModel):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'pending', 'resolved', 'closed', 'archived')",
            name="chk_conversations_status",
        ),
        CheckConstraint("btrim(visitor_id) <> ''", name="chk_conversations_visitor_id_nonblank"),
        Index("ix_conversations_business_visitor", "business_id", "visitor_id"),
        Index("ix_conversations_business_status", "business_id", "status"),
        Index("ix_conversations_business_status_last_message", "business_id", "status", "last_message_at"),
        {
            "comment": (
                "Tenant-scoped customer interaction thread. "
                "Customer identity belongs in contacts/contact_identities."
            )
        },
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    first_response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visitor_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Unverified display metadata from inbound clients; do not use for trusted identity decisions.
    visitor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Unverified inbound metadata; canonical email identity belongs in contact_identities.
    visitor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    next_message_sequence: Mapped[int] = mapped_column(nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ConversationStatus.OPEN.value)

    business: Mapped["Business"] = relationship("Business", back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        foreign_keys="Message.conversation_id",
        order_by="Message.conversation_sequence, Message.created_at",
        lazy="raise",
    )

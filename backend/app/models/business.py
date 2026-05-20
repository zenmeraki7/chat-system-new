import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.business_domains import (
        BusinessMembership,
        BusinessApiKey,
        BusinessWidgetSettings,
        BusinessAiSettings,
        MetaBusinessAccount,
        WhatsAppBusinessAccount,
        OAuthCredential,
        WebhookSubscription,
    )


class Business(BaseModel):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    public_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    onboarding_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    billing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="trial")
    business_type: Mapped[str] = mapped_column(String(30), nullable=False, default="MERCHANT")
    data_region: Mapped[str] = mapped_column(String(10), nullable=False, default="US")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    default_locale: Mapped[str] = mapped_column(String(20), nullable=False, default="en")

    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="business", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["BusinessMembership"]] = relationship(
        "BusinessMembership", back_populates="business", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["BusinessApiKey"]] = relationship(
        "BusinessApiKey", back_populates="business", cascade="all, delete-orphan"
    )
    widget_settings: Mapped["BusinessWidgetSettings"] = relationship(
        "BusinessWidgetSettings", back_populates="business", cascade="all, delete-orphan", uselist=False
    )
    ai_settings: Mapped["BusinessAiSettings"] = relationship(
        "BusinessAiSettings", back_populates="business", cascade="all, delete-orphan", uselist=False
    )
    meta_business_accounts: Mapped[list["MetaBusinessAccount"]] = relationship(
        "MetaBusinessAccount", back_populates="business", cascade="all, delete-orphan"
    )
    whatsapp_business_accounts: Mapped[list["WhatsAppBusinessAccount"]] = relationship(
        "WhatsAppBusinessAccount", back_populates="business", cascade="all, delete-orphan"
    )
    oauth_credentials: Mapped[list["OAuthCredential"]] = relationship(
        "OAuthCredential", back_populates="business", cascade="all, delete-orphan"
    )
    webhook_subscriptions: Mapped[list["WebhookSubscription"]] = relationship(
        "WebhookSubscription", back_populates="business", cascade="all, delete-orphan"
    )

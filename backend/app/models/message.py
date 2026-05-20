import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import (
    Enum,
    ForeignKey,
    Text,
    String,
    DateTime,
    ForeignKeyConstraint,
    UniqueConstraint,
    Index,
    text,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"
    SYSTEM = "system"


class MessageSenderType(str, enum.Enum):
    CONTACT = "contact"
    USER = "user"
    BOT = "bot"
    SYSTEM = "system"
    PROVIDER = "provider"


class MessageKind(str, enum.Enum):
    TEXT = "text"
    TEMPLATE = "template"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT_CARD = "contact_card"
    INTERACTIVE = "interactive"
    SYSTEM_EVENT = "system_event"
    INTERNAL_NOTE = "internal_note"


class MessageStatus(str, enum.Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageFailureCategory(str, enum.Enum):
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    INVALID_RECIPIENT = "invalid_recipient"
    TEMPLATE_NOT_APPROVED = "template_not_approved"
    TOKEN_REVOKED = "token_revoked"
    PHONE_NUMBER_DISABLED = "phone_number_disabled"
    BILLING_BLOCKED = "billing_blocked"
    POLICY_VIOLATION = "policy_violation"
    NETWORK_TIMEOUT = "network_timeout"
    UNKNOWN = "unknown"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "conversation_id"],
            ["conversations.business_id", "conversations.id"],
            ondelete="RESTRICT",
            name="fk_messages_conversation_tenant",
        ),
        UniqueConstraint(
            "business_id",
            "provider",
            "provider_message_id",
            name="uq_messages_provider_message",
        ),
        UniqueConstraint(
            "business_id",
            "idempotency_key",
            name="uq_messages_business_idempotency",
        ),
        Index("ix_messages_business_conversation", "business_id", "conversation_id"),
        Index("ix_messages_business_conversation_created", "business_id", "conversation_id", "created_at", "id"),
        Index("ix_messages_business_provider_message", "business_id", "provider", "provider_message_id"),
        Index("ix_messages_business_campaign", "business_id", "campaign_id"),
        Index(
            "uq_campaign_snapshot_item_message",
            "business_id",
            "campaign_snapshot_item_id",
            unique=True,
            postgresql_where=text("campaign_snapshot_item_id IS NOT NULL"),
        ),
        Index(
            "uq_inbound_provider_message",
            "business_id",
            "provider",
            "provider_message_id",
            unique=True,
            postgresql_where=text("direction = 'inbound' AND provider_message_id IS NOT NULL"),
        ),
        Index(
            "uq_outbound_message_idempotency",
            "business_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("direction = 'outbound' AND idempotency_key IS NOT NULL"),
        ),
        UniqueConstraint(
            "business_id",
            "conversation_id",
            "conversation_sequence",
            name="uq_messages_conversation_sequence",
        ),
        UniqueConstraint("business_id", "id", name="uq_messages_business_id_id"),
        CheckConstraint(
            "content_text IS NULL OR char_length(content_text) <= 8192",
            name="chk_messages_content_text_len",
        ),
        CheckConstraint(
            "rendered_preview_text IS NULL OR char_length(rendered_preview_text) <= 8192",
            name="chk_messages_rendered_preview_text_len",
        ),
        CheckConstraint(
            "content IS NULL OR btrim(content) <> ''",
            name="chk_messages_content_not_blank",
        ),
        UniqueConstraint(
            "business_id",
            "message_group_id",
            "group_sequence",
            name="uq_messages_group_sequence",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(
            MessageDirection,
            name="message_direction",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
        default=MessageDirection.OUTBOUND,
        server_default=MessageDirection.OUTBOUND.value,
    )
    sender_type: Mapped[MessageSenderType] = mapped_column(
        Enum(
            MessageSenderType,
            name="message_sender_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
        default=MessageSenderType.SYSTEM,
        server_default=MessageSenderType.SYSTEM.value,
    )
    message_kind: Mapped[MessageKind] = mapped_column(
        Enum(
            MessageKind,
            name="message_kind",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
        default=MessageKind.TEXT,
        server_default=MessageKind.TEXT.value,
    )
    channel_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_recipient_snapshots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_snapshot_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_recipient_snapshot_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_message_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    template_category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    template_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_approval_snapshots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_components_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    template_variables_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rendered_preview_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    client_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    send_operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_from_webhook_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_sequence: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[MessageStatus] = mapped_column(
        Enum(
            MessageStatus,
            name="message_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
        default=MessageStatus.QUEUED,
        server_default=MessageStatus.QUEUED.value,
    )
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="customer_visible", server_default="customer_visible")
    opt_in_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="SET NULL"), nullable=True, index=True
    )
    send_policy_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("send_policy_decisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    billing_classification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_price_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_pricing_window_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_pricing_windows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    usage_ledger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usage_ledger.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    api_client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_category: Mapped[MessageFailureCategory | None] = mapped_column(
        Enum(
            MessageFailureCategory,
            name="message_failure_category",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            validate_strings=True,
        ),
        nullable=True,
    )
    retryable: Mapped[bool | None] = mapped_column(nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interactive_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    interactive_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    selected_button_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    selected_list_row_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    location_latitude: Mapped[float | None] = mapped_column(nullable=True)
    location_longitude: Mapped[float | None] = mapped_column(nullable=True)
    reaction_to_provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    referral_source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    unsupported_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    actor_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    ai_response_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_prompt_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    knowledge_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    safety_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    handoff_decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redacted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    redaction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_redaction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    contains_pii: Mapped[bool | None] = mapped_column(nullable=True)
    moderation_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    redaction_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    role: Mapped[MessageRole | None] = mapped_column(
        Enum(MessageRole, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_source_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    render_source_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    render_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    message_group_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    group_sequence: Mapped[int | None] = mapped_column(nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    provider_payload_redacted_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    provider_payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_payload_retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # legacy extension bag
    ingestion_source: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact_import_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    backfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
        lazy="raise",
    )

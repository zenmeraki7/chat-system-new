import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, DateTime, text, UniqueConstraint, ForeignKeyConstraint, Index, event
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.business import Business


class User(BaseModel):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_rehash_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memberships: Mapped[list["BusinessMembership"]] = relationship(
        "BusinessMembership", back_populates="user", cascade="all, delete-orphan"
    )


class Role(BaseModel):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission", back_populates="role", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["BusinessMembership"]] = relationship("BusinessMembership", back_populates="role")


class Permission(BaseModel):
    __tablename__ = "permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    role: Mapped["Role"] = relationship("Role", back_populates="permissions")


class BusinessMembership(BaseModel):
    __tablename__ = "business_memberships"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role_code: Mapped[str] = mapped_column(String(30), nullable=False, default="member")
    is_primary_owner: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    business: Mapped["Business"] = relationship("Business", back_populates="memberships")
    user: Mapped["User"] = relationship("User", back_populates="memberships")
    role: Mapped["Role"] = relationship("Role", back_populates="memberships")


class MembershipInvite(BaseModel):
    __tablename__ = "membership_invites"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invite_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BusinessApiKey(BaseModel):
    __tablename__ = "business_api_keys"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="Default key")
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")

    business: Mapped["Business"] = relationship("Business", back_populates="api_keys")


class BusinessWidgetSettings(BaseModel):
    __tablename__ = "business_widget_settings"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    widget_theme_preset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("widget_theme_presets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    widget_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6366f1")
    widget_title: Mapped[str] = mapped_column(String(100), nullable=False, default="Chat with us")
    business: Mapped["Business"] = relationship("Business", back_populates="widget_settings")


class BusinessAiSettings(BaseModel):
    __tablename__ = "business_ai_settings"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    business: Mapped["Business"] = relationship("Business", back_populates="ai_settings")


class MetaBusinessAccount(BaseModel):
    __tablename__ = "meta_business_accounts"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meta_business_account_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    business: Mapped["Business"] = relationship("Business", back_populates="meta_business_accounts")


class WhatsAppBusinessAccount(BaseModel):
    __tablename__ = "whatsapp_business_accounts"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    waba_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_health_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_successful_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_template_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    business: Mapped["Business"] = relationship("Business", back_populates="whatsapp_business_accounts")


class WhatsAppPhoneNumber(BaseModel):
    __tablename__ = "whatsapp_phone_numbers"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_rating: Mapped[str | None] = mapped_column(String(30), nullable=True)
    messaging_limit_tier: Mapped[str | None] = mapped_column(String(60), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    is_default_for_sending: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_default_for_inbox: Mapped[bool] = mapped_column(nullable=False, default=False)
    sending_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_health_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_successful_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_template_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PhoneNumberAssignment(BaseModel):
    __tablename__ = "phone_number_assignments"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    waba_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class EmbeddedSignupSession(BaseModel):
    __tablename__ = "embedded_signup_sessions"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    expected_origin: Mapped[str] = mapped_column(String(255), nullable=False)
    received_code_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OAuthCredential(BaseModel):
    __tablename__ = "oauth_credentials"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    credential_owner_type: Mapped[str] = mapped_column(String(30), nullable=False, default="business")
    credential_owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    grant_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    credential_purpose: Mapped[str | None] = mapped_column(String(80), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_service: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_health_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_successful_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_template_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    business: Mapped["Business"] = relationship("Business", back_populates="oauth_credentials")


class WebhookSubscription(BaseModel):
    __tablename__ = "webhook_subscriptions"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    waba_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    verify_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscribed_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_health_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_successful_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_template_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    business: Mapped["Business"] = relationship("Business", back_populates="webhook_subscriptions")


class WebhookEvent(BaseModel):
    __tablename__ = "webhook_events"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")


class OutboundMessage(BaseModel):
    __tablename__ = "outbound_messages"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")


class MessageOutbox(BaseModel):
    __tablename__ = "message_outbox"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_message_outbox_idempotency_key"),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_recipients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    to_phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_message_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown", index=True)
    priority: Mapped[int] = mapped_column(nullable=False, default=100, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class OutboundMessageAttempt(BaseModel):
    __tablename__ = "outbound_message_attempts"
    outbound_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbound_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_api_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MessageStatusEvent(BaseModel):
    __tablename__ = "message_status_events"
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    outbound_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbound_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    received_webhook_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    pricing_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    conversation_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    errors_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class MessageSendAttempt(BaseModel):
    __tablename__ = "message_send_attempts"
    __table_args__ = (
        UniqueConstraint("business_id", "message_id", "attempt_number", name="uq_message_send_attempt_number"),
        ForeignKeyConstraint(
            ["business_id", "message_id"],
            ["messages.business_id", "messages.id"],
            ondelete="RESTRICT",
            name="fk_message_send_attempts_message_tenant",
        ),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oauth_credentials.id", ondelete="SET NULL"), nullable=True, index=True
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    response_status_code: Mapped[int | None] = mapped_column(nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_error_subcode: Mapped[str | None] = mapped_column(String(120), nullable=True)
    response_body_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retryable: Mapped[bool | None] = mapped_column(nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class WhatsAppMessageMetadata(BaseModel):
    __tablename__ = "whatsapp_message_metadata"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    customer_wa_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    waba_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


class WebhookProcessingAttempt(BaseModel):
    __tablename__ = "webhook_processing_attempts"
    webhook_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebhookDeadLetter(BaseModel):
    __tablename__ = "webhook_dead_letters"
    webhook_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_events.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class PhoneRegistrationAttempt(BaseModel):
    __tablename__ = "phone_registration_attempts"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    waba_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    onboarding_operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    outbox_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbox_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False, default=1)
    result_status: Mapped[str] = mapped_column(String(30), nullable=False)
    http_status_code: Mapped[int | None] = mapped_column(nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_error_subcode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    response_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class OnboardingEventLedger(BaseModel):
    __tablename__ = "onboarding_event_ledger"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    event_status: Mapped[str] = mapped_column(String(30), nullable=False, default="info")
    merchant_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    waba_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    meta_app_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    graph_api_endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    graph_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    graph_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    graph_error_subcode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fbtrace_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    graph_response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Campaign(BaseModel):
    __tablename__ = "campaigns"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    waba_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    public_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False, default="broadcast")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_message_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    template_category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    variable_mapping_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation_saved_views.id", ondelete="SET NULL"), nullable=True, index=True
    )
    csv_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contact_import_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    total_recipients: Mapped[int] = mapped_column(nullable=False, default=0)
    eligible_recipients: Mapped[int] = mapped_column(nullable=False, default=0)
    skipped_recipients: Mapped[int] = mapped_column(nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(nullable=False, default=0)
    delivered_count: Mapped[int] = mapped_column(nullable=False, default=0)
    read_count: Mapped[int] = mapped_column(nullable=False, default=0)
    replied_count: Mapped[int] = mapped_column(nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(nullable=False, default=0)
    estimated_cost: Mapped[float | None] = mapped_column(nullable=True)
    reserved_amount: Mapped[float | None] = mapped_column(nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(nullable=True)
    preview_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    campaign_config_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    preview_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preview_invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CampaignRecipientSnapshot(BaseModel):
    __tablename__ = "campaign_recipient_snapshots"
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_set_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    recipients: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CampaignRecipientSnapshotItem(BaseModel):
    __tablename__ = "campaign_recipient_snapshot_items"
    campaign_recipient_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaign_recipient_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")


class CampaignRecipient(BaseModel):
    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_e164", name="uq_campaign_recipients_campaign_phone"),
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    wa_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    eligibility_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    eligibility_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    variables_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rendered_template_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(nullable=True)
    reserved_amount: Mapped[float | None] = mapped_column(nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CampaignRecipientEvent(BaseModel):
    __tablename__ = "campaign_recipient_events"
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_recipients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CampaignSendJob(BaseModel):
    __tablename__ = "campaign_send_jobs"
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_recipients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CampaignSendAttempt(BaseModel):
    __tablename__ = "campaign_send_attempts"
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaign_recipient_snapshot_items.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CampaignStatusEvent(BaseModel):
    __tablename__ = "campaign_status_events"
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CampaignExecutionEvent(BaseModel):
    __tablename__ = "campaign_execution_events"
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True)


class UsageLedger(BaseModel):
    __tablename__ = "usage_ledger"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    usage_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)


class BillingLedger(BaseModel):
    __tablename__ = "billing_ledger"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_recipients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_outbox.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[float] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="posted")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class AuditLog(BaseModel):
    __tablename__ = "audit_logs"
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="success")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BillingAccount(BaseModel):
    __tablename__ = "billing_accounts"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    tax_region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class BusinessComplianceProfile(BaseModel):
    __tablename__ = "business_compliance_profiles"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tax_region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    data_region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retention_policy: Mapped[str | None] = mapped_column(String(80), nullable=True)


class BusinessOnboardingStep(BaseModel):
    __tablename__ = "business_onboarding_steps"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EmailVerificationToken(BaseModel):
    __tablename__ = "email_verification_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)


class PasswordResetToken(BaseModel):
    __tablename__ = "password_reset_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)


class UserSession(BaseModel):
    __tablename__ = "user_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserLoginAttempt(BaseModel):
    __tablename__ = "user_login_attempts"
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    attempted_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class IdentityProvider(BaseModel):
    __tablename__ = "identity_providers"
    business_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class ExternalIdentity(BaseModel):
    __tablename__ = "external_identities"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class BusinessProfile(BaseModel):
    __tablename__ = "business_profiles"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    support_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    support_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tax_id_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)


class Subscription(BaseModel):
    __tablename__ = "subscriptions"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Entitlement(BaseModel):
    __tablename__ = "entitlements"
    feature_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class BusinessEntitlement(BaseModel):
    __tablename__ = "business_entitlements"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    limit_value: Mapped[int | None] = mapped_column(nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeatureFlag(BaseModel):
    __tablename__ = "feature_flags"
    feature_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class BusinessFeatureFlag(BaseModel):
    __tablename__ = "business_feature_flags"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    variant: Mapped[str | None] = mapped_column(String(80), nullable=True)
    configured_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)


class BusinessStatusEvent(BaseModel):
    __tablename__ = "business_status_events"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)


class WhatsAppAssetConnectionEvent(BaseModel):
    __tablename__ = "whatsapp_asset_connection_events"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    meta_business_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_meta_response_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class WhatsAppIntegration(BaseModel):
    __tablename__ = "whatsapp_integrations"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="connected")
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessLegalAcceptance(BaseModel):
    __tablename__ = "business_legal_acceptances"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    document_version: Mapped[str] = mapped_column(String(80), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class WhatsAppAssetTransfer(BaseModel):
    __tablename__ = "whatsapp_asset_transfers"
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    from_business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    to_business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Brand(BaseModel):
    __tablename__ = "brands"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class BrandChannel(BaseModel):
    __tablename__ = "brand_channels"
    brand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    whatsapp_phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    widget_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("business_widget_settings.id", ondelete="SET NULL"), nullable=True, index=True)


class Channel(BaseModel):
    __tablename__ = "channels"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    external_channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class WhatsAppChannel(BaseModel):
    __tablename__ = "whatsapp_channels"
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    waba_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


class WebchatChannel(BaseModel):
    __tablename__ = "webchat_channels"
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    widget_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("business_widget_settings.id", ondelete="SET NULL"), nullable=True, index=True)


class InstagramChannel(BaseModel):
    __tablename__ = "instagram_channels"
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    instagram_business_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


class EmailChannel(BaseModel):
    __tablename__ = "email_channels"
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    email_address: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


class Team(BaseModel):
    __tablename__ = "teams"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class Inbox(BaseModel):
    __tablename__ = "inboxes"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(40), nullable=False, default="omni")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class Agent(BaseModel):
    __tablename__ = "agents"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="offline")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TeamMember(BaseModel):
    __tablename__ = "team_members"
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="member")


class ConversationAssignment(BaseModel):
    __tablename__ = "conversation_assignments"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class ConversationStatusEvent(BaseModel):
    __tablename__ = "conversation_status_events"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)


class ConversationTag(BaseModel):
    __tablename__ = "conversation_tags"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    tag: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class InternalNote(BaseModel):
    __tablename__ = "internal_notes"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)


class InternalNoteMention(BaseModel):
    __tablename__ = "internal_note_mentions"
    internal_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("internal_notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mentioned_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mention_text: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ConversationTypingPresence(BaseModel):
    __tablename__ = "conversation_typing_presence"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="typing")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ConversationSavedView(BaseModel):
    __tablename__ = "conversation_saved_views"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filters_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="private")


class SlaPolicy(BaseModel):
    __tablename__ = "sla_policies"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    response_minutes: Mapped[int] = mapped_column(nullable=False, default=15)
    resolution_minutes: Mapped[int] = mapped_column(nullable=False, default=240)


class ConversationAutomationState(BaseModel):
    __tablename__ = "conversation_automation_state"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    ai_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    handoff_status: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    handoff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ai_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContactOptIn(BaseModel):
    __tablename__ = "contact_opt_ins"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    opt_in_status: Mapped[str] = mapped_column(String(30), nullable=False, default="opted_out")
    opt_in_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    opt_in_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    opted_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WhatsAppMessageTemplate(BaseModel):
    __tablename__ = "whatsapp_message_templates"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    waba_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    meta_template_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    components_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MediaAsset(BaseModel):
    __tablename__ = "media_assets"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scan_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    access_policy: Mapped[str] = mapped_column(String(40), nullable=False, default="private")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PhoneNumberRateLimitState(BaseModel):
    __tablename__ = "phone_number_rate_limit_state"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    current_tier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quality_rating: Mapped[str | None] = mapped_column(String(40), nullable=True)
    messages_sent_window: Mapped[int] = mapped_column(nullable=False, default=0)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_limit_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class BusinessRestriction(BaseModel):
    __tablename__ = "business_restrictions"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    restricted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessAiSettingVersion(BaseModel):
    __tablename__ = "business_ai_setting_versions"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    setting_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WidgetSettingVersion(BaseModel):
    __tablename__ = "widget_setting_versions"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    setting_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    widget_color: Mapped[str] = mapped_column(String(20), nullable=False)
    widget_title: Mapped[str] = mapped_column(String(100), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAccessGrant(BaseModel):
    __tablename__ = "admin_access_grants"
    admin_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAccessAuditLog(BaseModel):
    __tablename__ = "admin_access_audit_logs"
    admin_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)


class WebhookSecret(BaseModel):
    __tablename__ = "webhook_secrets"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_version: Mapped[int] = mapped_column(nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderSyncRun(BaseModel):
    __tablename__ = "provider_sync_runs"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sync_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderSyncItem(BaseModel):
    __tablename__ = "provider_sync_items"
    sync_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("provider_sync_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")


class ProviderAsset(BaseModel):
    __tablename__ = "provider_assets"
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PiiClassificationRule(BaseModel):
    __tablename__ = "pii_classification_rules"
    table_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    column_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    retention_policy: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ContactImportJob(BaseModel):
    __tablename__ = "contact_import_jobs"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)


class ContactImportRow(BaseModel):
    __tablename__ = "contact_import_rows"
    import_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contact_import_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")


class ContactImportError(BaseModel):
    __tablename__ = "contact_import_errors"
    import_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contact_import_rows.id", ondelete="CASCADE"), nullable=False, index=True)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)


class ContactDeduplicationKey(BaseModel):
    __tablename__ = "contact_deduplication_keys"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class Contact(BaseModel):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_business_updated_id", "business_id", "updated_at", "id"),
        Index("ix_contacts_business_phone", "business_id", "normalized_phone"),
        Index("ix_contacts_business_optin_updated_id", "business_id", "opt_in_status", "updated_at", "id"),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wa_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    custom_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    opt_in_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    opt_in_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    opt_in_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    display_name_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    display_name_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContactIdentity(BaseModel):
    __tablename__ = "contact_identities"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    provider_identity_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    provider_identity_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    identity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    identity_value_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unverified")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SuppressionListEntry(BaseModel):
    __tablename__ = "suppression_list_entries"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    identity_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)


class OutboxEvent(BaseModel):
    __tablename__ = "outbox_events"
    business_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    queue_region: Mapped[str] = mapped_column(String(16), nullable=False, default="global", index=True)
    queue_domain: Mapped[str] = mapped_column(String(40), nullable=False, default="generic", index=True)
    workload_class: Mapped[str] = mapped_column(String(20), nullable=False, default="cold", index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _derive_outbox_domain_and_workload(event_type: str | None) -> tuple[str, str]:
    normalized = str(event_type or "").strip().lower()
    if normalized.startswith("webhook."):
        return "webhooks", "hot"
    if normalized in {"whatsapp.send.outbound", "campaign_dispatch_job", "campaign_batch_dispatch_job"}:
        return "send", "hot"
    if normalized.startswith("conversation."):
        return "inbox", "hot"
    if normalized.startswith("campaign.") or normalized.startswith("bulk_job."):
        return "campaign", "cold"
    if normalized.startswith("contact_export."):
        return "exports", "cold"
    return "generic", "cold"


@event.listens_for(OutboxEvent, "before_insert")
def _outbox_event_default_classifier(mapper, connection, target: OutboxEvent) -> None:
    domain, workload = _derive_outbox_domain_and_workload(getattr(target, "event_type", None))
    if not getattr(target, "queue_domain", None):
        target.queue_domain = domain
    if not getattr(target, "workload_class", None):
        target.workload_class = workload
    if not getattr(target, "queue_region", None):
        target.queue_region = "global"


class Workspace(BaseModel):
    __tablename__ = "workspaces"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    data_region: Mapped[str] = mapped_column(String(10), nullable=False, default="US")


class WorkspaceMembership(BaseModel):
    __tablename__ = "workspace_memberships"
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class Seat(BaseModel):
    __tablename__ = "seats"
    business_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=True, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    seat_type: Mapped[str] = mapped_column(String(40), nullable=False, default="agent")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContactSource(BaseModel):
    __tablename__ = "contact_sources"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    first_seen_channel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContactMergeEvent(BaseModel):
    __tablename__ = "contact_merge_events"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    source_contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    target_contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    merged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)


class ConversationParticipant(BaseModel):
    __tablename__ = "conversation_participants"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    participant_type: Mapped[str] = mapped_column(String(30), nullable=False)
    participant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ConversationEvent(BaseModel):
    __tablename__ = "conversation_events"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class ConversationNote(BaseModel):
    __tablename__ = "conversation_notes"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)


class ConversationMessage(BaseModel):
    __tablename__ = "conversation_messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)


class AutomationFlow(BaseModel):
    __tablename__ = "automation_flows"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class AutomationFlowVersion(BaseModel):
    __tablename__ = "automation_flow_versions"
    automation_flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("automation_flows.id", ondelete="CASCADE"), nullable=False, index=True)
    flow_version: Mapped[int] = mapped_column(nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")


class AutomationExecution(BaseModel):
    __tablename__ = "automation_executions"
    automation_flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("automation_flows.id", ondelete="CASCADE"), nullable=False, index=True)
    flow_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    context_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class AutomationExecutionStep(BaseModel):
    __tablename__ = "automation_execution_steps"
    automation_execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("automation_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    details_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Bot(BaseModel):
    __tablename__ = "bots"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class BotVersion(BaseModel):
    __tablename__ = "bot_versions"
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    bot_version: Mapped[int] = mapped_column(nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")


class BotChannelAssignment(BaseModel):
    __tablename__ = "bot_channel_assignments"
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class BotGuardrail(BaseModel):
    __tablename__ = "bot_guardrails"
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_type: Mapped[str] = mapped_column(String(60), nullable=False)
    rule_value: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeSource(BaseModel):
    __tablename__ = "knowledge_sources"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="workspace")


class KnowledgeDocument(BaseModel):
    __tablename__ = "knowledge_documents"
    knowledge_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class KnowledgeChunk(BaseModel):
    __tablename__ = "knowledge_chunks"
    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class KnowledgeSyncRun(BaseModel):
    __tablename__ = "knowledge_sync_runs"
    knowledge_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiPromptVersion(BaseModel):
    __tablename__ = "ai_prompt_versions"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    prompt_version: Mapped[int] = mapped_column(nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PricingCatalog(BaseModel):
    __tablename__ = "pricing_catalogs"
    business_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class PricingCatalogVersion(BaseModel):
    __tablename__ = "pricing_catalog_versions"
    pricing_catalog_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pricing_catalogs.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessagePriceRule(BaseModel):
    __tablename__ = "message_price_rules"
    pricing_catalog_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pricing_catalog_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    conversation_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    unit_price: Mapped[float] = mapped_column(nullable=False)


class ProviderIntegration(BaseModel):
    __tablename__ = "provider_integrations"
    business_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    api_version: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class BusinessRateLimitPolicy(BaseModel):
    __tablename__ = "business_rate_limit_policies"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    limit: Mapped[int] = mapped_column(nullable=False)
    window_seconds: Mapped[int] = mapped_column(nullable=False)


class IdempotencyRecord(BaseModel):
    __tablename__ = "idempotency_records"
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OnboardingStatusEvent(BaseModel):
    __tablename__ = "onboarding_status_events"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step: Mapped[str] = mapped_column(String(80), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubscriptionStatusEvent(BaseModel):
    __tablename__ = "subscription_status_events"
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LegalHold(BaseModel):
    __tablename__ = "legal_holds"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    placed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImpersonationSession(BaseModel):
    __tablename__ = "impersonation_sessions"
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiClient(BaseModel):
    __tablename__ = "api_clients"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="live")


class ApiClientKey(BaseModel):
    __tablename__ = "api_client_keys"
    api_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiClientScope(BaseModel):
    __tablename__ = "api_client_scopes"
    api_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(120), nullable=False, index=True)


class ApiClientRateLimit(BaseModel):
    __tablename__ = "api_client_rate_limits"
    api_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    limit: Mapped[int] = mapped_column(nullable=False)
    window_seconds: Mapped[int] = mapped_column(nullable=False)


class CustomerWebhookEndpoint(BaseModel):
    __tablename__ = "customer_webhook_endpoints"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    signing_secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscribed_events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class CustomerWebhookDelivery(BaseModel):
    __tablename__ = "customer_webhook_deliveries"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerWebhookDeliveryAttempt(BaseModel):
    __tablename__ = "customer_webhook_delivery_attempts"
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_webhook_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ProviderRequestLog(BaseModel):
    __tablename__ = "provider_request_logs"
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oauth_credentials.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    request_correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider_response_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    response_status: Mapped[int | None] = mapped_column(nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    retryable: Mapped[bool] = mapped_column(nullable=False, default=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ProviderErrorMapping(BaseModel):
    __tablename__ = "provider_error_mappings"
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    error_subcode: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    retry_policy: Mapped[str] = mapped_column(String(40), nullable=False)
    user_visible_message: Mapped[str] = mapped_column(Text, nullable=False)


class BusinessProfileVersion(BaseModel):
    __tablename__ = "business_profile_versions"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    support_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WidgetThemePreset(BaseModel):
    __tablename__ = "widget_theme_presets"
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class BrandWidgetSetting(BaseModel):
    __tablename__ = "brand_widget_settings"
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    widget_theme_preset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("widget_theme_presets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    widget_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6366f1")
    widget_title: Mapped[str] = mapped_column(String(100), nullable=False, default="Chat with us")


class BusinessSettings(BaseModel):
    __tablename__ = "business_settings"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    active_widget_settings_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("widget_setting_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    active_ai_settings_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_ai_setting_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )


class ProviderAccount(BaseModel):
    __tablename__ = "provider_accounts"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class BusinessProviderAssetLink(BaseModel):
    __tablename__ = "business_provider_asset_links"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    link_status: Mapped[str] = mapped_column(String(30), nullable=False, default="linked")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verified_by_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oauth_credentials.id", ondelete="SET NULL"), nullable=True, index=True
    )


class OperationLock(BaseModel):
    __tablename__ = "operation_locks"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lock_name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_token: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ProviderWebhookEvent(BaseModel):
    __tablename__ = "provider_webhook_events"
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ComplianceEvidence(BaseModel):
    __tablename__ = "compliance_evidence"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    evidence_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class SendingPolicy(BaseModel):
    __tablename__ = "sending_policies"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    allowed_days: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    policy_scope: Mapped[str] = mapped_column(String(40), nullable=False, default="outbound")


class SendPolicyDecision(BaseModel):
    __tablename__ = "send_policy_decisions"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="allow")
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ContactSendCounter(BaseModel):
    __tablename__ = "contact_send_counters"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    messages_sent: Mapped[int] = mapped_column(nullable=False, default=0)


class ContactMessageFrequency(BaseModel):
    __tablename__ = "contact_message_frequency"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    marketing_messages_24h: Mapped[int] = mapped_column(nullable=False, default=0)
    marketing_messages_7d: Mapped[int] = mapped_column(nullable=False, default=0)
    marketing_messages_30d: Mapped[int] = mapped_column(nullable=False, default=0)
    last_marketing_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class DangerousActionConfirmation(BaseModel):
    __tablename__ = "dangerous_action_confirmations"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confirmation_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OnboardingOperation(BaseModel):
    __tablename__ = "onboarding_operations"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    current_step: Mapped[str | None] = mapped_column(String(80), nullable=True)
    compensating_action_required: Mapped[bool] = mapped_column(nullable=False, default=False)


class WhatsAppConnection(BaseModel):
    __tablename__ = "whatsapp_connections"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="connected")
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WhatsAppPricingWindow(BaseModel):
    __tablename__ = "whatsapp_pricing_windows"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_wa_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_by_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )


class CampaignApprovalSnapshot(BaseModel):
    __tablename__ = "campaign_approval_snapshots"
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    recipient_count: Mapped[int] = mapped_column(nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(nullable=True)
    compliance_acknowledged: Mapped[bool] = mapped_column(nullable=False, default=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MessageEvent(BaseModel):
    __tablename__ = "message_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "message_id"],
            ["messages.business_id", "messages.id"],
            ondelete="RESTRICT",
            name="fk_message_events_message_tenant",
        ),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class MessageModerationResult(BaseModel):
    __tablename__ = "message_moderation_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "message_id"],
            ["messages.business_id", "messages.id"],
            ondelete="RESTRICT",
            name="fk_message_moderation_results_message_tenant",
        ),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    moderation_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    categories_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class MessageSearchDocument(BaseModel):
    __tablename__ = "message_search_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "message_id"],
            ["messages.business_id", "messages.id"],
            ondelete="RESTRICT",
            name="fk_message_search_documents_message_tenant",
        ),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    search_document: Mapped[str] = mapped_column(Text, nullable=False)

class BusinessEvent(BaseModel):
    __tablename__ = "business_events"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class KillSwitch(BaseModel):
    __tablename__ = "kill_switches"
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    scope_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobOperation(BaseModel):
    __tablename__ = "job_operations"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")


class QuerySnapshot(BaseModel):
    __tablename__ = "query_snapshots"
    __table_args__ = (
        UniqueConstraint("business_id", "resource", "query_hash", name="uq_query_snapshots_business_resource_hash"),
        Index("ix_query_snapshots_business_resource_status", "business_id", "resource", "status", "created_at", "id"),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    query_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    query_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class ContactExportJob(BaseModel):
    __tablename__ = "contact_export_jobs"
    __table_args__ = (
        Index("ix_contact_export_jobs_business_status_created", "business_id", "status", "created_at", "id"),
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    query_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("query_snapshots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    selection_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="explicit")
    selected_contact_ids_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    excluded_contact_ids_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    columns_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    progress: Mapped[int] = mapped_column(nullable=False, default=0)
    total_rows: Mapped[int] = mapped_column(nullable=False, default=0)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    download_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class BusinessDashboardStat(BaseModel):
    __tablename__ = "business_dashboard_stats"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metrics_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class ConversationInboxView(BaseModel):
    __tablename__ = "conversation_inbox_view"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class CampaignSummaryStat(BaseModel):
    __tablename__ = "campaign_summary_stats"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    stats_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PhoneNumberHealthSummary(BaseModel):
    __tablename__ = "phone_number_health_summary"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    summary_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    health_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BillingUsageDaily(BaseModel):
    __tablename__ = "billing_usage_daily"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usage_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usage_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class MessageMetricsDaily(BaseModel):
    __tablename__ = "message_metrics_daily"
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    date_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    dimension_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sent_count: Mapped[int] = mapped_column(nullable=False, default=0)
    delivered_count: Mapped[int] = mapped_column(nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(nullable=False, default=0)

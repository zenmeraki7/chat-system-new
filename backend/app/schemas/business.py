import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BusinessProfileResponse(BaseModel):
    public_id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MetaOAuthCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=10, max_length=2048)
    state: str = Field(min_length=20, max_length=512)
    waba_id: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^\d+$")
    phone_number_id: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^\d+$")


class WhatsAppOnboardingStatusResponse(BaseModel):
    integration_status: str
    business_id: uuid.UUID
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    display_phone_number: Optional[str] = None
    verified_name: Optional[str] = None
    quality_rating: Optional[str] = None
    messaging_limit_tier: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    verification_status: Optional[str] = None
    permissions_granted: list[str] = []
    token_expires_at: Optional[datetime] = None
    token_valid: bool = False


class WhatsAppOnboardingProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_phone_e164: Optional[str] = Field(default=None, min_length=8, max_length=20)
    probe_text: Optional[str] = Field(default=None, min_length=1, max_length=1024)


class WhatsAppOnboardingProbeResponse(BaseModel):
    status: str
    message_outbox_id: uuid.UUID
    idempotency_key: str
    recipient: str


class WhatsAppOperationalProjectionResponse(BaseModel):
    business_id: uuid.UUID
    credential_health: str
    subscription_health: str
    phone_readiness: str
    webhook_heartbeat: str
    probe_send: str
    unified_state: str
    reason: str


class WhatsAppOperationalReadinessResponse(BaseModel):
    embedded_signup_completed: bool
    code_exchanged: bool
    token_valid: bool
    required_scopes_granted: bool
    business_fetch_ok: bool
    waba_fetch_ok: bool
    phone_fetch_ok: bool
    phone_belongs_to_waba: bool
    waba_subscribed_to_app: bool
    messages_webhook_enabled: bool
    webhook_last_received_at: Optional[datetime] = None
    phone_registered: bool
    can_send_test_message: bool
    can_receive_webhook: bool
    templates_fetch_ok: bool
    final_status: str


class WhatsAppDiagnosticsResponse(BaseModel):
    business_id: uuid.UUID
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    token_valid: bool
    required_scopes: list[str]
    waba_fetch_ok: bool
    phone_numbers_fetch_ok: bool
    subscribed_apps_ok: bool
    messages_webhook_enabled: bool
    phone_registered: bool
    last_webhook_received_at: Optional[datetime] = None
    last_inbound_message_received_at: Optional[datetime] = None
    test_send_result: str


class OnboardingEventLogItem(BaseModel):
    created_at: datetime
    event_type: str
    event_status: str
    operation_id: Optional[str] = None
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    graph_api_endpoint: Optional[str] = None
    graph_error_code: Optional[str] = None
    graph_error_subcode: Optional[str] = None
    fbtrace_id: Optional[str] = None
    trace_id: Optional[str] = None
    error_message: Optional[str] = None


class WebhookInboxDebugItem(BaseModel):
    event_id: str
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    message_id: Optional[str] = None
    direction: Optional[str] = None
    payload_type: Optional[str] = None
    received_at: datetime
    signature_valid: bool
    processed_status: str
    error: Optional[str] = None


class WhatsAppSetupDiagnosticsResponse(BaseModel):
    business_id: uuid.UUID
    waba_id: Optional[str] = None
    template_sync_status: str
    template_total_count: int = 0
    template_approved_count: int = 0
    template_pending_count: int = 0
    template_last_synced_at: Optional[datetime] = None
    webhook_subscription_status: str
    webhook_last_received_at: Optional[datetime] = None
    webhook_heartbeat_status: str
    webhook_heartbeat_lag_seconds: Optional[int] = None


class OnboardingOperationDebugResponse(BaseModel):
    operation_id: Optional[str] = None
    status: Optional[str] = None
    current_step: Optional[str] = None
    compensating_action_required: Optional[bool] = None


class OAuthCredentialDebugResponse(BaseModel):
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    last_health_status: Optional[str] = None
    last_health_error_code: Optional[str] = None
    scopes: list[str] = []


class WebhookSubscriptionDebugResponse(BaseModel):
    status: Optional[str] = None
    subscribed_fields: list[str] = []
    last_webhook_received_at: Optional[datetime] = None
    last_health_status: Optional[str] = None
    last_health_error_code: Optional[str] = None


class RegistrationOutboxEventDebugResponse(BaseModel):
    id: str
    status: str
    attempts: int
    available_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    payload: dict = {}


class WhatsAppOnboardingDebugResponse(BaseModel):
    integration_status: Optional[str] = None
    onboarding_operation: OnboardingOperationDebugResponse
    credential: OAuthCredentialDebugResponse
    webhook: WebhookSubscriptionDebugResponse
    registration_outbox_events: list[RegistrationOutboxEventDebugResponse] = []

class EmbeddedSignupSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_origin: str = Field(min_length=1, max_length=255)
    ttl_minutes: int = Field(default=15, ge=5, le=60)


class EmbeddedSignupSessionCreateResponse(BaseModel):
    onboarding_session_id: uuid.UUID
    state: str
    expected_origin: str
    expires_at: datetime


class SelectWhatsAppPhoneNumberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    onboarding_session_id: uuid.UUID
    waba_id: str = Field(min_length=1, max_length=64, pattern=r"^\d+$")
    phone_number_id: str = Field(min_length=1, max_length=64, pattern=r"^\d+$")


class BusinessProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class BusinessAISettingsResponse(BaseModel):
    system_prompt: str
    prompt_version: int
    updated_at: datetime


class BusinessAISettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: Optional[str] = Field(default=None, min_length=1, max_length=8000)


class WidgetSettingsResponse(BaseModel):
    widget_color: str
    widget_title: str
    updated_at: datetime


class WidgetSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    widget_title: Optional[str] = Field(default=None, min_length=1, max_length=60)


class WidgetScriptResponse(BaseModel):
    script_url: str
    widget_public_key: str
    business_public_id: uuid.UUID


class BusinessCreatedResponse(BaseModel):
    business: BusinessProfileResponse
    raw_key: str


class ApiKeyIssuedResponse(BaseModel):
    key_prefix: str
    raw_key: str

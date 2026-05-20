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

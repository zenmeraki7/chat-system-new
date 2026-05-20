import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CampaignTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_status: str = Field(min_length=1, max_length=40)
    reason: str | None = Field(default=None, max_length=500)


class CampaignTransitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: uuid.UUID
    status: str
    updated_at: datetime


class CampaignRecipientTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_status: str = Field(min_length=1, max_length=40)


class CampaignRecipientTransitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_id: uuid.UUID
    status: str
    updated_at: datetime


class CampaignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    phone_number_id: str = Field(min_length=1, max_length=255)
    template_id: uuid.UUID
    segment_id: uuid.UUID | None = None
    csv_import_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    type: str = Field(default="broadcast", pattern="^(broadcast|automation|abandoned_cart|followup)$")


class CampaignCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: uuid.UUID
    status: str
    name: str
    phone_number_id: str
    template_id: uuid.UUID
    template_name: str | None = None
    template_language: str | None = None
    template_category: str | None = None
    segment_id: uuid.UUID | None = None
    csv_import_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CampaignRecipientSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: str = Field(pattern="^(saved_segment|csv_upload)$")
    segment_id: uuid.UUID | None = None
    csv_import_id: uuid.UUID | None = None


class CampaignFinalizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: uuid.UUID
    status: str
    total_recipients: int
    eligible_recipients: int
    skipped_recipients: int
    validation_errors: list[dict] = []


class CampaignTemplateVariableMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable_mapping: dict[str, str]


class CampaignTemplateVariableValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: uuid.UUID
    valid: bool
    errors: list[dict] = []


class CampaignPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_recipients: int
    eligible_recipients: int
    skipped_recipients: int
    skips: dict
    estimated_cost: dict
    estimated_duration_minutes: int
    recipient_count: int
    eligibility_summary: dict
    variable_error_summary: dict
    country_cost_breakdown: list[dict]
    template_category: str | None = None
    template_preview: str | None = None
    sample_rendered_messages: list[dict] = []
    quality_rate_warnings: list[str] = []

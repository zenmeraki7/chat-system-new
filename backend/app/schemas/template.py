import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class TemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    waba_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    language: str = Field(min_length=1, max_length=20)
    category: str = Field(default="utility", max_length=60)
    status: str = Field(default="draft", max_length=30)
    components_json: dict = Field(default_factory=dict)
    meta_template_id: str | None = Field(default=None, max_length=255)
    rejection_reason: str | None = Field(default=None, max_length=2000)


class TemplateStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, max_length=30)
    rejection_reason: str | None = Field(default=None, max_length=2000)


class TemplateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    waba_id: str
    meta_template_id: str | None = None
    name: str
    language: str
    category: str | None = None
    status: str
    components_json: dict
    rejection_reason: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TemplateSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int
    approved_or_active: int
    pending_or_in_review: int
    rejected_or_paused: int
    draft_or_unknown: int

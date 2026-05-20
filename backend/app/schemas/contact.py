import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ContactUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_e164: str | None = None
    wa_id: str | None = None
    name: str | None = None
    email: str | None = None
    tags: list[str] = Field(default_factory=list)
    custom_attributes: dict = Field(default_factory=dict)
    source: str | None = None


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    phone_e164: str | None = None
    wa_id: str | None = None
    name: str | None = None
    email: str | None = None
    tags: list[str] = []
    custom_attributes: dict = {}
    opt_in_status: str
    opt_in_source: str | None = None
    opt_in_timestamp: datetime | None = None
    unsubscribed_at: datetime | None = None
    blocked_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_message_at: datetime | None = None
    marketing_eligible: bool


class ContactCSVValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str


class ContactMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_contact_id: uuid.UUID
    target_contact_id: uuid.UUID


class ContactOptInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opt_in_status: str = Field(pattern="^(opted_in|opted_out|unsubscribed|unknown)$")
    opt_in_source: str | None = None


class ContactBlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocked: bool


class ContactUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    email: str | None = None
    tags: list[str] | None = None
    custom_attributes: dict | None = None


class ContactSegmentFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags_any: list[str] = Field(default_factory=list)
    opt_in_status: str | None = None
    blocked: bool | None = None
    unsubscribed: bool | None = None
    has_email: bool | None = None
    has_wa_id: bool | None = None
    search: str | None = None


class ContactSegmentUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    filters: ContactSegmentFilter
    visibility: str = Field(default="private", pattern="^(private|team|business)$")


class ContactSegmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    name: str
    visibility: str
    filters: dict
    count: int


class ContactCsvImportExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str
    source_file_name: str | None = None


class ContactDuplicateSuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_contact_id: uuid.UUID
    target_contact_id: uuid.UUID
    score: int
    reasons: list[str]
    safe_to_merge: bool

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


class ContactListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str | None = None
    phone_number: str
    status: str
    created_at: datetime
    updated_at: datetime


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


class ContactAgentCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(
        pattern="^(add_tag|add_purchase|add_enquiry|add_follow_up|add_note|mark_hot_lead|mark_existing_customer|mark_walk_in_customer|mark_converted)$"
    )
    tag: str | None = Field(default=None, min_length=1, max_length=40)
    purchased_item: str | None = Field(default=None, min_length=1, max_length=180)
    amount: float | None = Field(default=None, ge=0, le=1000000000)
    next_follow_up: str | None = Field(default=None, min_length=1, max_length=250)
    note: str | None = Field(default=None, min_length=1, max_length=1000)
    captured_at: datetime | None = None


class ContactQrOptInCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_e164: str = Field(min_length=7, max_length=25)
    wa_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    branch: str = Field(min_length=1, max_length=120)
    source: str = Field(default="in_store_qr", min_length=1, max_length=80)
    prefilled_message: str = Field(default="JOIN", min_length=1, max_length=120)
    tags: list[str] = Field(default_factory=lambda: ["walk_in_customer"])


class ContactOfflineRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_e164: str = Field(min_length=7, max_length=25)
    name: str | None = Field(default=None, max_length=255)
    branch: str = Field(min_length=1, max_length=120)
    registration_type: str = Field(pattern="^(digital_bill|warranty|loyalty|exchange_policy|styling_tips|next_offer|service_appointment)$")
    product_purchased: str | None = Field(default=None, max_length=180)
    purchase_date: datetime | None = None
    warranty_until: datetime | None = None
    service_reminder_at: datetime | None = None
    consent_reply: str = Field(pattern="^(YES|NO)$")


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


class ContactExportJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: str = Field(pattern="^contacts$")
    columns: list[str] = Field(default_factory=list)
    selection_mode: str = Field(pattern="^snapshot$")
    query_snapshot_id: uuid.UUID
    operation_id: str = Field(min_length=1, max_length=120)


class ContactBulkSuppressPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_mode: str = Field(pattern="^snapshot$")
    query_snapshot_id: uuid.UUID
    operation_id: str = Field(min_length=1, max_length=120)


class ContactBulkSuppressConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=120)
    confirmation_hash: str = Field(min_length=16, max_length=128)


class ContactBulkTagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=120)
    selection_mode: str = Field(pattern="^snapshot$")
    query_snapshot_id: uuid.UUID
    action: str = Field(pattern="^(add|remove)$")
    tag: str = Field(min_length=1, max_length=80)

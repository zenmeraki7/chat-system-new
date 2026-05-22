import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models.conversation import ConversationStatus


class WidgetConversationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_public_key: str = Field(min_length=10, max_length=255)
    visitor_token: str | None = Field(default=None, max_length=512)
    visitor_name: str | None = Field(default=None, max_length=100)
    visitor_email: EmailStr | None = None

    @field_validator("visitor_name")
    @classmethod
    def normalize_visitor_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("visitor_email")
    @classmethod
    def normalize_visitor_email(cls, value: EmailStr | None) -> str | None:
        return str(value).strip().lower() if value else None


class PublicConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime


class ConversationInboxItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: uuid.UUID
    status: ConversationStatus
    visitor_name: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0
    assigned_user_id: uuid.UUID | None = None
    assigned_team_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    priority: str = "normal"
    tags: list[str] = []
    first_response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: uuid.UUID
    status: ConversationStatus
    visitor_name: str | None = None
    visitor_email: EmailStr | None = None
    message_count: int | None = None
    assigned_user_id: uuid.UUID | None = None
    assigned_team_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ConversationProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visitor_name: str | None = Field(default=None, max_length=100)
    visitor_email: EmailStr | None = None

    @field_validator("visitor_name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("visitor_email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        return str(value).strip().lower() if value else None


class CloseConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str | None = Field(default=None, max_length=100)
    reason_note: str | None = Field(default=None, max_length=500)


class ReopenConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_note: str | None = Field(default=None, max_length=500)


class AssignConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_public_id: uuid.UUID | None = None
    assigned_team_id: uuid.UUID | None = None


class AddConversationTagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str = Field(min_length=1, max_length=64)


class AddInternalNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=5000)
    mentioned_user_ids: list[uuid.UUID] = Field(default_factory=list)


class InboxSavedViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    filters_json: dict = Field(default_factory=dict)
    visibility: str = Field(default="private", pattern="^(private|team|business)$")


class TypingPresenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(default="typing", pattern="^(typing|replying|idle)$")
    ttl_seconds: int = Field(default=20, ge=5, le=120)


class SlaPolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    response_minutes: int = Field(ge=1, le=10080)
    resolution_minutes: int = Field(ge=1, le=10080)


class ApplySlaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_name: str | None = Field(default=None, max_length=120)


class ConversationTimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    created_at: datetime
    payload: dict


class WorkloadRoutingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: str = Field(default="queue_routing", pattern="^(queue_routing|round_robin|capacity)$")
    team_id: uuid.UUID | None = None
    eligible_user_ids: list[uuid.UUID] = Field(default_factory=list)
    max_capacity_per_agent: int = Field(default=20, ge=1, le=1000)


class WorkloadRoutingDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assigned_user_id: uuid.UUID | None = None
    assigned_team_id: uuid.UUID | None = None
    strategy: str
    open_load_for_assigned_user: int | None = None

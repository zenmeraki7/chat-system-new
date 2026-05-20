import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.message import MessageDirection, MessageKind, MessageSenderType, MessageStatus


class MessageAttachmentResponse(BaseModel):
    media_type: str
    file_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    download_url: str | None = None


class PublicMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: uuid.UUID
    conversation_public_id: uuid.UUID
    direction: MessageDirection
    sender_type: MessageSenderType
    message_type: MessageKind
    content_text: str | None = None
    status: MessageStatus | None = None
    created_at: datetime
    is_redacted: bool = False


class AgentMessageResponse(PublicMessageResponse):
    sender_name: str | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    failed_at: datetime | None = None
    attachments: list[MessageAttachmentResponse] = []


class SendTextMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_text: str = Field(min_length=1, max_length=4096)
    idempotency_key: str = Field(min_length=16, max_length=128)
    reply_to_message_public_id: uuid.UUID | None = None

    @field_validator("content_text")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content is required")
        return normalized

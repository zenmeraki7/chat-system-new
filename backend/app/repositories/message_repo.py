from typing import AsyncIterator, List, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
from uuid import UUID
import hashlib
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import load_only
from sqlalchemy.exc import IntegrityError
from app.models.business_domains import UsageLedger
from app.core.exceptions import ForbiddenException
from app.models.message import Message, MessageRole, MessageDirection, MessageSenderType, MessageKind, MessageStatus


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_conversation(
        self, business_id: UUID, conversation_id: UUID, limit: int = 50
    ) -> List[Message]:
        # Backward-compatible wrapper; prefer list_page_for_conversation for cursor-based history.
        limit = min(max(limit, 1), 100)
        result = await self.db.execute(
            select(Message)
            .where(
                Message.business_id == business_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_message_previews_for_conversation(
        self,
        *,
        business_id: UUID,
        conversation_id: UUID,
        before_sequence: int | None = None,
        limit: int = 50,
    ) -> List[Message]:
        limit = min(max(limit, 1), 100)
        stmt = (
            select(Message)
            .options(
                load_only(
                    Message.id,
                    Message.business_id,
                    Message.conversation_id,
                    Message.conversation_sequence,
                    Message.direction,
                    Message.sender_type,
                    Message.message_kind,
                    Message.status,
                    Message.created_at,
                    Message.sent_at,
                    Message.delivered_at,
                    Message.read_at,
                    Message.content_text,
                    Message.provider,
                    Message.provider_message_id,
                )
            )
            .where(
                Message.business_id == business_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
        )
        if before_sequence is not None:
            stmt = stmt.where(Message.conversation_sequence < before_sequence)
        stmt = stmt.order_by(Message.conversation_sequence.desc(), Message.id.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_page_for_conversation(
        self,
        *,
        business_id: UUID,
        conversation_id: UUID,
        before_sequence: int | None = None,
        limit: int = 50,
    ) -> List[Message]:
        limit = min(max(limit, 1), 100)
        stmt = select(Message).where(
            Message.business_id == business_id,
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
        )
        if before_sequence is not None:
            stmt = stmt.where(Message.conversation_sequence < before_sequence)
        stmt = stmt.order_by(Message.conversation_sequence.desc(), Message.id.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_for_business(self, business_id: UUID, message_id: UUID) -> Message | None:
        result = await self.db.execute(
            select(Message).where(
                Message.business_id == business_id,
                Message.id == message_id,
                Message.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, *, business_id: UUID, message_id: UUID) -> Message | None:
        result = await self.db.execute(
            select(Message)
            .where(
                Message.business_id == business_id,
                Message.id == message_id,
                Message.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_message(
        self,
        business_id: UUID,
        conversation_id: UUID,
        role: MessageRole,
        content: str,
        meta: Optional[dict] = None,
        conversation_sequence: Optional[int] = None,
        channel_id: Optional[UUID] = None,
        contact_id: Optional[UUID] = None,
        idempotency_key: Optional[str] = None,
        provider_message_id: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Message:
        if role == MessageRole.USER:
            return await self.create_inbound_once(
                business_id=business_id,
                conversation_id=conversation_id,
                content_text=content,
                provider_payload=meta,
                conversation_sequence=conversation_sequence,
                channel_id=channel_id,
                contact_id=contact_id,
                provider=provider,
                provider_message_id=provider_message_id,
                idempotency_key=idempotency_key,
                source_type="webhook",
            )
        return await self.create_outbound_once(
            business_id=business_id,
            conversation_id=conversation_id,
            role=role,
            content_text=content,
            provider_payload=meta,
            conversation_sequence=conversation_sequence,
            channel_id=channel_id,
            contact_id=contact_id,
            idempotency_key=idempotency_key,
            provider=provider,
            provider_message_id=provider_message_id,
            source_type="ai_reply" if role == MessageRole.ASSISTANT else "system",
        )

    async def create_inbound_once(
        self,
        *,
        business_id: UUID,
        conversation_id: UUID,
        content_text: str,
        provider_payload: Optional[dict] = None,
        conversation_sequence: Optional[int] = None,
        channel_id: Optional[UUID] = None,
        contact_id: Optional[UUID] = None,
        provider: Optional[str] = None,
        provider_message_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        created_from_webhook_event_id: Optional[UUID] = None,
        campaign_id: Optional[UUID] = None,
        campaign_snapshot_item_id: Optional[UUID] = None,
        template_snapshot_id: Optional[UUID] = None,
        media_asset_id: Optional[UUID] = None,
        pricing_window_id: Optional[UUID] = None,
        usage_ledger_id: Optional[UUID] = None,
        source_type: str = "webhook",
        source_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        actor_type: str = "provider",
        actor_id: Optional[str] = None,
    ) -> Message:
        normalized_content = content_text.strip() if content_text is not None else ""
        if not normalized_content:
            raise ValueError("content must not be blank for text messages")
        if len(normalized_content) > 8192:
            raise ValueError("content exceeds maximum supported length for text messages")
        try:
            async with self.db.begin_nested():
                row = Message(
                    business_id=business_id,
                    conversation_id=conversation_id,
                    direction=MessageDirection.INBOUND,
                    sender_type=MessageSenderType.CONTACT,
                    message_kind=MessageKind.TEXT,
                    status=MessageStatus.QUEUED,
                    queued_at=datetime.now(timezone.utc),
                    role=MessageRole.USER,
                    content=normalized_content,
                    content_text=normalized_content,
                    provider_payload=provider_payload,
                    conversation_sequence=conversation_sequence,
                    channel_id=channel_id,
                    contact_id=contact_id,
                    provider=provider,
                    provider_message_id=provider_message_id,
                    idempotency_key=idempotency_key,
                    created_from_webhook_event_id=created_from_webhook_event_id,
                    campaign_id=campaign_id,
                    campaign_snapshot_item_id=campaign_snapshot_item_id,
                    template_snapshot_id=template_snapshot_id,
                    media_asset_id=media_asset_id,
                    conversation_pricing_window_id=pricing_window_id,
                    usage_ledger_id=usage_ledger_id,
                    source_type=source_type,
                    source_id=source_id,
                    operation_id=operation_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    content_hash=hashlib.sha256(normalized_content.encode("utf-8")).hexdigest(),
                )
                self.db.add(row)
                await self.db.flush()
                return row
        except IntegrityError:
            existing = None
            if provider_message_id and provider:
                existing = await self.get_by_provider_message_id(
                    business_id=business_id,
                    provider=provider,
                    provider_message_id=provider_message_id,
                )
            if not existing and idempotency_key:
                existing = await self.get_by_idempotency_key(
                    business_id=business_id,
                    idempotency_key=idempotency_key,
                )
            if existing:
                return existing
            raise

    async def create_outbound_once(
        self,
        *,
        business_id: UUID,
        conversation_id: UUID,
        role: MessageRole = MessageRole.ASSISTANT,
        content_text: str,
        provider_payload: Optional[dict] = None,
        conversation_sequence: Optional[int] = None,
        channel_id: Optional[UUID] = None,
        contact_id: Optional[UUID] = None,
        idempotency_key: Optional[str] = None,
        provider: Optional[str] = None,
        provider_message_id: Optional[str] = None,
        send_operation_id: Optional[str] = None,
        client_message_id: Optional[str] = None,
        campaign_id: Optional[UUID] = None,
        campaign_snapshot_item_id: Optional[UUID] = None,
        template_snapshot_id: Optional[UUID] = None,
        media_asset_id: Optional[UUID] = None,
        pricing_window_id: Optional[UUID] = None,
        usage_ledger_id: Optional[UUID] = None,
        source_type: str = "api",
        source_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        actor_type: str = "api_client",
        actor_id: Optional[str] = None,
    ) -> Message:
        normalized_content = content_text.strip() if content_text is not None else ""
        if not normalized_content:
            raise ValueError("content must not be blank for text messages")
        if len(normalized_content) > 8192:
            raise ValueError("content exceeds maximum supported length for text messages")
        try:
            async with self.db.begin_nested():
                row = Message(
                    business_id=business_id,
                    conversation_id=conversation_id,
                    direction=MessageDirection.OUTBOUND,
                    sender_type=MessageSenderType.BOT if role == MessageRole.ASSISTANT else MessageSenderType.SYSTEM,
                    message_kind=MessageKind.TEXT,
                    status=MessageStatus.QUEUED,
                    queued_at=datetime.now(timezone.utc),
                    role=role,
                    content=normalized_content,
                    content_text=normalized_content,
                    provider_payload=provider_payload,
                    conversation_sequence=conversation_sequence,
                    channel_id=channel_id,
                    contact_id=contact_id,
                    idempotency_key=idempotency_key,
                    provider=provider,
                    provider_message_id=provider_message_id,
                    send_operation_id=send_operation_id,
                    client_message_id=client_message_id,
                    campaign_id=campaign_id,
                    campaign_snapshot_item_id=campaign_snapshot_item_id,
                    template_snapshot_id=template_snapshot_id,
                    media_asset_id=media_asset_id,
                    conversation_pricing_window_id=pricing_window_id,
                    usage_ledger_id=usage_ledger_id,
                    source_type=source_type,
                    source_id=source_id,
                    operation_id=operation_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    content_hash=hashlib.sha256(normalized_content.encode("utf-8")).hexdigest(),
                )
                self.db.add(row)
                await self.db.flush()
                return row
        except IntegrityError:
            existing = None
            if idempotency_key:
                existing = await self.get_by_idempotency_key(
                    business_id=business_id,
                    idempotency_key=idempotency_key,
                )
            if not existing and provider_message_id and provider:
                existing = await self.get_by_provider_message_id(
                    business_id=business_id,
                    provider=provider,
                    provider_message_id=provider_message_id,
                )
            if existing:
                return existing
            raise

    async def get_by_idempotency_key(self, *, business_id: UUID, idempotency_key: str) -> Message | None:
        result = await self.db.execute(
            select(Message).where(
                Message.business_id == business_id,
                Message.idempotency_key == idempotency_key,
                Message.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_provider_message_id(self, *, business_id: UUID, provider: str, provider_message_id: str) -> Message | None:
        result = await self.db.execute(
            select(Message).where(
                Message.business_id == business_id,
                Message.provider == provider,
                Message.provider_message_id == provider_message_id,
                Message.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def transition_status_if_current_in(
        self,
        *,
        business_id: UUID,
        message_id: UUID,
        allowed_previous_statuses: set[MessageStatus] | set[str],
        new_status: MessageStatus,
        provider_timestamp: datetime | None = None,
    ) -> Message | None:
        if not allowed_previous_statuses:
            raise ValueError("allowed_previous_statuses cannot be empty")
        normalized_previous = {
            s.value if isinstance(s, MessageStatus) else str(s).lower()
            for s in allowed_previous_statuses
        }
        values = {"status": new_status}
        ts = provider_timestamp or datetime.now(timezone.utc)
        if new_status == MessageStatus.SENT:
            values["sent_at"] = ts
        elif new_status == MessageStatus.DELIVERED:
            values["delivered_at"] = ts
        elif new_status == MessageStatus.READ:
            values["read_at"] = ts
        elif new_status == MessageStatus.FAILED:
            values["failed_at"] = ts
        stmt = (
            update(Message)
            .where(
                Message.business_id == business_id,
                Message.id == message_id,
                Message.deleted_at.is_(None),
                Message.status.in_(normalized_previous),
            )
            .values(**values)
            .returning(Message)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_for_business_with_version(
        self,
        *,
        business_id: UUID,
        message_id: UUID,
        expected_version: int,
        values: dict,
    ) -> Message | None:
        if not values:
            raise ValueError("No update fields provided")
        allowed_fields = {
            "visibility",
            "content_redacted_at",
            "content_redaction_reason",
            "moderation_status",
            "redaction_status",
            "retention_until",
            "status",
        }
        unknown_fields = set(values.keys()) - allowed_fields
        if unknown_fields:
            raise ValueError(f"Unknown or forbidden update fields: {', '.join(sorted(unknown_fields))}")
        stmt = (
            update(Message)
            .where(
                Message.business_id == business_id,
                Message.id == message_id,
                Message.version == expected_version,
                Message.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1)
            .returning(Message)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_by_conversation(self, business_id: UUID, conversation_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                Message.business_id == business_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
        )
        return result.scalar_one()

    async def stream_for_conversation(
        self,
        *,
        business_id: UUID,
        conversation_id: UUID,
    ) -> AsyncIterator[Message]:
        stmt = (
            select(Message)
            .where(
                Message.business_id == business_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
            .order_by(Message.conversation_sequence.asc(), Message.id.asc())
        )
        result = await self.db.stream(stmt)
        async for row in result.scalars():
            yield row

    async def delete(self, id: UUID) -> bool:
        raise ForbiddenException("Hard delete is not supported for messages; use redaction/soft-delete workflows")

    class SoftDeleteStatus(str, Enum):
        DELETED = "deleted"
        NOT_FOUND = "not_found"
        BLOCKED_BY_USAGE_LEDGER = "blocked_by_usage_ledger"

    @dataclass(frozen=True)
    class SoftDeleteResult:
        status: "MessageRepository.SoftDeleteStatus"
        message_id: UUID

        @property
        def deleted(self) -> bool:
            return self.status == MessageRepository.SoftDeleteStatus.DELETED

    async def soft_delete_for_business_result(self, *, business_id: UUID, id: UUID) -> "SoftDeleteResult":
        target = await self.get_for_business(business_id, id)
        if target is None:
            return MessageRepository.SoftDeleteResult(
                status=MessageRepository.SoftDeleteStatus.NOT_FOUND,
                message_id=id,
            )
        if target.deleted_at is not None:
            return MessageRepository.SoftDeleteResult(
                status=MessageRepository.SoftDeleteStatus.NOT_FOUND,
                message_id=id,
            )
        usage_link = await self.db.execute(
            select(UsageLedger.id).where(UsageLedger.source_type == "message", UsageLedger.source_id == str(id)).limit(1)
        )
        if usage_link.scalar_one_or_none() is not None:
            return MessageRepository.SoftDeleteResult(
                status=MessageRepository.SoftDeleteStatus.BLOCKED_BY_USAGE_LEDGER,
                message_id=id,
            )
        await self.db.execute(
            update(Message)
            .where(
                Message.business_id == business_id,
                Message.id == id,
                Message.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return MessageRepository.SoftDeleteResult(
            status=MessageRepository.SoftDeleteStatus.DELETED,
            message_id=id,
        )

    async def soft_delete_for_business(self, *, business_id: UUID, id: UUID) -> bool:
        result = await self.soft_delete_for_business_result(business_id=business_id, id=id)
        if result.status == MessageRepository.SoftDeleteStatus.BLOCKED_BY_USAGE_LEDGER:
            raise ForbiddenException("Cannot soft-delete billable message; use content redaction flow")
        return result.deleted

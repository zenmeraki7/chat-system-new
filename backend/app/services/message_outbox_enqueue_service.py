from __future__ import annotations

from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import MessageOutbox


class MessageOutboxEnqueueService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def enqueue_text(
        self,
        *,
        business_id: UUID,
        phone_number_id: str,
        to_phone_e164: str,
        text: str,
        idempotency_key: str,
        source: str,
        priority: int = 100,
        scheduled_at: datetime | None = None,
        campaign_id: UUID | None = None,
        campaign_recipient_id: UUID | None = None,
        conversation_id: UUID | None = None,
        template_id: UUID | None = None,
        extra_payload: dict | None = None,
    ) -> MessageOutbox:
        existing = (
            await self.db.execute(
                select(MessageOutbox).where(
                    MessageOutbox.idempotency_key == idempotency_key,
                    MessageOutbox.deleted_at.is_(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        row = MessageOutbox(
            business_id=business_id,
            campaign_id=campaign_id,
            campaign_recipient_id=campaign_recipient_id,
            conversation_id=conversation_id,
            phone_number_id=phone_number_id,
            to_phone_e164=to_phone_e164,
            message_type="text",
            template_id=template_id,
            payload_json={
                "text": text,
                "source": source,
                **(extra_payload or {}),
            },
            source_type=source,
            priority=max(1, int(priority)),
            scheduled_at=scheduled_at or datetime.now(timezone.utc),
            idempotency_key=idempotency_key,
            status="pending",
            attempt_count=0,
        )
        self.db.add(row)
        await self.db.flush()
        return row

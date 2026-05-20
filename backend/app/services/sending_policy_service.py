from app.models.business_domains import SendingPolicy, ContactSendCounter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ForbiddenException
from datetime import datetime, timezone


class SendingPolicyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def assert_allowed_now(self, business_id):
        row = (await self.db.execute(select(SendingPolicy).where(SendingPolicy.business_id == business_id, SendingPolicy.deleted_at.is_(None)))).scalars().first()
        if not row or not row.quiet_hours_start or not row.quiet_hours_end:
            return
        now = datetime.now(timezone.utc)
        hhmm = now.strftime("%H:%M")
        if row.quiet_hours_start <= hhmm <= row.quiet_hours_end:
            raise ForbiddenException("Blocked by quiet-hours policy")

    async def assert_frequency_cap(self, business_id, contact_id: str, channel_type: str, max_messages: int):
        row = (await self.db.execute(select(ContactSendCounter).where(
            ContactSendCounter.business_id == business_id,
            ContactSendCounter.contact_id == contact_id,
            ContactSendCounter.channel_type == channel_type,
            ContactSendCounter.deleted_at.is_(None),
        ))).scalars().first()
        if row and row.messages_sent >= max_messages:
            raise ForbiddenException("Blocked by frequency cap")

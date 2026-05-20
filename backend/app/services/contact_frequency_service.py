from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.models.business_domains import (
    BusinessRateLimitPolicy,
    Contact,
    ContactMessageFrequency,
    ContactSource,
)


@dataclass
class MarketingCaps:
    per_day: int = 1
    per_week: int = 3
    per_30d: int = 10


class ContactFrequencyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _merchant_caps(self, business_id: UUID) -> MarketingCaps:
        rows = (
            await self.db.execute(
                select(BusinessRateLimitPolicy).where(
                    BusinessRateLimitPolicy.business_id == business_id,
                    BusinessRateLimitPolicy.deleted_at.is_(None),
                    BusinessRateLimitPolicy.scope.in_(
                        ["marketing_cap_24h", "marketing_cap_7d", "marketing_cap_30d"]
                    ),
                )
            )
        ).scalars().all()
        caps = MarketingCaps()
        for r in rows:
            scope = (r.scope or "").lower()
            if scope == "marketing_cap_24h":
                caps.per_day = max(0, int(r.limit or caps.per_day))
            elif scope == "marketing_cap_7d":
                caps.per_week = max(0, int(r.limit or caps.per_week))
            elif scope == "marketing_cap_30d":
                caps.per_30d = max(0, int(r.limit or caps.per_30d))
        return caps

    async def _is_cold_imported_contact(self, business_id: UUID, contact_id: UUID | None) -> bool:
        if contact_id is None:
            return False
        contact = (
            await self.db.execute(
                select(Contact).where(
                    Contact.id == contact_id,
                    Contact.business_id == business_id,
                    Contact.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if contact is None:
            return False
        if contact.last_seen_at is not None or contact.last_message_at is not None:
            return False
        source = (
            await self.db.execute(
                select(ContactSource).where(
                    ContactSource.contact_id == contact_id,
                    ContactSource.business_id == business_id,
                    ContactSource.deleted_at.is_(None),
                ).order_by(ContactSource.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if source is None:
            return False
        return (source.source or "").lower() in {"csv_import", "import", "bulk_import"}

    async def _load_or_create_row(self, *, business_id: UUID, contact_key: str, phone_e164: str) -> ContactMessageFrequency:
        row = (
            await self.db.execute(
                select(ContactMessageFrequency).where(
                    ContactMessageFrequency.business_id == business_id,
                    ContactMessageFrequency.contact_id == contact_key,
                    ContactMessageFrequency.deleted_at.is_(None),
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            row = ContactMessageFrequency(
                business_id=business_id,
                contact_id=contact_key,
                phone_e164=phone_e164,
                marketing_messages_24h=0,
                marketing_messages_7d=0,
                marketing_messages_30d=0,
                last_marketing_message_at=None,
            )
            self.db.add(row)
            await self.db.flush()
        return row

    async def assert_can_send_marketing(
        self,
        *,
        business_id: UUID,
        contact_id: UUID | None,
        phone_e164: str,
    ) -> None:
        contact_key = str(contact_id) if contact_id else phone_e164
        row = await self._load_or_create_row(business_id=business_id, contact_key=contact_key, phone_e164=phone_e164)
        caps = await self._merchant_caps(business_id)
        cold = await self._is_cold_imported_contact(business_id, contact_id)
        if cold:
            # Stricter caps for cold imported contacts.
            caps = MarketingCaps(per_day=min(caps.per_day, 1), per_week=min(caps.per_week, 2), per_30d=min(caps.per_30d, 4))

        now = datetime.now(timezone.utc)
        last = row.last_marketing_message_at
        if last is None or (now - last) >= timedelta(days=30):
            row.marketing_messages_24h = 0
            row.marketing_messages_7d = 0
            row.marketing_messages_30d = 0
        else:
            if (now - last) >= timedelta(days=7):
                row.marketing_messages_7d = 0
            if (now - last) >= timedelta(days=1):
                row.marketing_messages_24h = 0

        if row.marketing_messages_24h >= caps.per_day:
            raise ForbiddenException("Blocked by marketing frequency cap (24h)")
        if row.marketing_messages_7d >= caps.per_week:
            raise ForbiddenException("Blocked by marketing frequency cap (7d)")
        if row.marketing_messages_30d >= caps.per_30d:
            raise ForbiddenException("Blocked by marketing frequency cap (30d)")

    async def record_marketing_send(
        self,
        *,
        business_id: UUID,
        contact_id: UUID | None,
        phone_e164: str,
    ) -> None:
        contact_key = str(contact_id) if contact_id else phone_e164
        row = await self._load_or_create_row(business_id=business_id, contact_key=contact_key, phone_e164=phone_e164)
        now = datetime.now(timezone.utc)
        last = row.last_marketing_message_at
        if last is None or (now - last) >= timedelta(days=30):
            row.marketing_messages_24h = 0
            row.marketing_messages_7d = 0
            row.marketing_messages_30d = 0
        else:
            if (now - last) >= timedelta(days=7):
                row.marketing_messages_7d = 0
            if (now - last) >= timedelta(days=1):
                row.marketing_messages_24h = 0
        row.marketing_messages_24h = int(row.marketing_messages_24h or 0) + 1
        row.marketing_messages_7d = int(row.marketing_messages_7d or 0) + 1
        row.marketing_messages_30d = int(row.marketing_messages_30d or 0) + 1
        row.last_marketing_message_at = now
        row.phone_e164 = phone_e164
        await self.db.flush()


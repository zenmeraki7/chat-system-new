from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.business_domains import Contact, ContactMergeEvent, ContactSource


class ContactRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_business(self, business_id: UUID, limit: int = 100):
        res = await self.db.execute(
            select(Contact).where(Contact.business_id == business_id, Contact.deleted_at.is_(None)).order_by(Contact.updated_at.desc()).limit(limit)
        )
        return list(res.scalars().all())

    async def get_by_id_for_business(self, business_id: UUID, contact_id: UUID):
        res = await self.db.execute(
            select(Contact).where(Contact.business_id == business_id, Contact.id == contact_id, Contact.deleted_at.is_(None))
        )
        return res.scalar_one_or_none()

    async def find_by_phone_or_wa(self, business_id: UUID, phone_e164: str | None, wa_id: str | None):
        if not phone_e164 and not wa_id:
            return None
        stmt = select(Contact).where(Contact.business_id == business_id, Contact.deleted_at.is_(None))
        if phone_e164 and wa_id:
            stmt = stmt.where((Contact.normalized_phone == phone_e164) | (Contact.wa_id == wa_id))
        elif phone_e164:
            stmt = stmt.where(Contact.normalized_phone == phone_e164)
        else:
            stmt = stmt.where(Contact.wa_id == wa_id)
        res = await self.db.execute(stmt.limit(1))
        return res.scalars().first()

    async def upsert_contact(
        self,
        *,
        business_id: UUID,
        phone_e164: str | None,
        wa_id: str | None,
        name: str | None,
        email: str | None,
        tags: list[str] | None,
        custom_attributes: dict | None,
        source: str | None,
    ) -> Contact:
        existing = await self.find_by_phone_or_wa(business_id, phone_e164, wa_id)
        now = datetime.now(timezone.utc)
        if existing:
            existing.normalized_phone = phone_e164 or existing.normalized_phone
            existing.wa_id = wa_id or existing.wa_id
            existing.display_name = name or existing.display_name
            existing.email = email or existing.email
            if tags is not None:
                merged = set(existing.tags or [])
                merged.update(tags)
                existing.tags = sorted(merged)
            if custom_attributes:
                merged_attrs = dict(existing.custom_attributes or {})
                merged_attrs.update(custom_attributes)
                existing.custom_attributes = merged_attrs
            existing.last_seen_at = now
            await self.db.flush()
            return existing

        row = Contact(
            business_id=business_id,
            normalized_phone=phone_e164,
            wa_id=wa_id,
            display_name=name,
            email=email,
            tags=tags or [],
            custom_attributes=custom_attributes or {},
            last_seen_at=now,
            status="active",
        )
        self.db.add(row)
        await self.db.flush()
        if source:
            self.db.add(ContactSource(business_id=business_id, contact_id=row.id, source=source))
        return row

    async def set_opt_in(self, *, business_id: UUID, contact_id: UUID, status: str, source: str | None):
        row = await self.get_by_id_for_business(business_id, contact_id)
        if not row:
            return None
        row.opt_in_status = status
        row.opt_in_source = source
        row.opt_in_timestamp = datetime.now(timezone.utc)
        if status == "unsubscribed":
            row.unsubscribed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return row

    async def set_blocked(self, *, business_id: UUID, contact_id: UUID, blocked: bool):
        row = await self.get_by_id_for_business(business_id, contact_id)
        if not row:
            return None
        row.blocked_at = datetime.now(timezone.utc) if blocked else None
        await self.db.flush()
        return row

    async def merge_contacts(self, *, business_id: UUID, source_contact_id: UUID, target_contact_id: UUID, merged_by_user_id: UUID | None):
        source = await self.get_by_id_for_business(business_id, source_contact_id)
        target = await self.get_by_id_for_business(business_id, target_contact_id)
        if not source or not target:
            return None
        target.tags = sorted(set((target.tags or []) + (source.tags or [])))
        merged_attrs = dict(source.custom_attributes or {})
        merged_attrs.update(target.custom_attributes or {})
        target.custom_attributes = merged_attrs
        target.last_message_at = max([d for d in [target.last_message_at, source.last_message_at] if d is not None], default=target.last_message_at)
        target.last_seen_at = max([d for d in [target.last_seen_at, source.last_seen_at] if d is not None], default=target.last_seen_at)
        source.archived_at = datetime.now(timezone.utc)
        source.status = "merged"
        self.db.add(
            ContactMergeEvent(
                business_id=business_id,
                source_contact_id=source.id,
                target_contact_id=target.id,
                merged_by_user_id=merged_by_user_id,
            )
        )
        await self.db.flush()
        return target


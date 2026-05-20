from __future__ import annotations

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.models.business_domains import Contact


class ContactSegmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_filters(self, stmt, filters: dict):
        if filters.get("opt_in_status"):
            stmt = stmt.where(Contact.opt_in_status == filters["opt_in_status"])
        if filters.get("blocked") is True:
            stmt = stmt.where(Contact.blocked_at.is_not(None))
        elif filters.get("blocked") is False:
            stmt = stmt.where(Contact.blocked_at.is_(None))
        if filters.get("unsubscribed") is True:
            stmt = stmt.where(Contact.unsubscribed_at.is_not(None))
        elif filters.get("unsubscribed") is False:
            stmt = stmt.where(Contact.unsubscribed_at.is_(None))
        if filters.get("has_email") is True:
            stmt = stmt.where(Contact.email.is_not(None))
        elif filters.get("has_email") is False:
            stmt = stmt.where(Contact.email.is_(None))
        if filters.get("has_wa_id") is True:
            stmt = stmt.where(Contact.wa_id.is_not(None))
        elif filters.get("has_wa_id") is False:
            stmt = stmt.where(Contact.wa_id.is_(None))
        tags_any = [t.strip().lower() for t in (filters.get("tags_any") or []) if t and t.strip()]
        if tags_any:
            for tag in tags_any:
                stmt = stmt.where(Contact.tags.contains([tag]))
        search = (filters.get("search") or "").strip()
        if search:
            q = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Contact.display_name.ilike(q),
                    Contact.email.ilike(q),
                    Contact.normalized_phone.ilike(q),
                    Contact.wa_id.ilike(q),
                )
            )
        return stmt

    async def count_contacts(self, business_id: UUID, filters: dict) -> int:
        stmt = select(func.count(Contact.id)).where(Contact.business_id == business_id, Contact.deleted_at.is_(None))
        stmt = self._apply_filters(stmt, filters)
        res = await self.db.execute(stmt)
        return int(res.scalar_one())

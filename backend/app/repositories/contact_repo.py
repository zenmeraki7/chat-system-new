from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.filters.contact_filters import CONTACT_FILTERS
from app.models.business_domains import Contact, ContactMergeEvent, ContactSource
from app.services.filter_compiler import FilterCompiler
from app.sorting.contact_sorts import CONTACT_SORTS
from app.utils.cursor_conditions import build_cursor_condition
from app.utils.search import normalize_search
from app.utils.sorting import build_order_by, resolve_sort, ResolvedSort


class ContactRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_business(self, business_id: UUID, limit: int = 100):
        res = await self.db.execute(
            select(Contact).where(Contact.business_id == business_id, Contact.deleted_at.is_(None)).order_by(Contact.updated_at.desc()).limit(limit)
        )
        return list(res.scalars().all())

    async def list_contacts_cursor(
        self,
        *,
        business_id: UUID,
        limit: int,
        sort_key: Optional[str],
        sort_dir: Optional[str],
        cursor_sort_value: Optional[object] = None,
        cursor_id: Optional[UUID] = None,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[Sequence[Contact], ResolvedSort]:
        resolved_sort = resolve_sort(
            sort_key=sort_key,
            sort_dir=sort_dir,
            sort_registry=CONTACT_SORTS,
            default_sort_key="updated_at",
        )

        conditions = [
            Contact.business_id == business_id,
            Contact.deleted_at.is_(None),
        ]

        if status:
            conditions.append(Contact.status == status)

        if search:
            normalized = f"%{search.strip()}%"
            conditions.append(
                or_(
                    Contact.display_name.ilike(normalized),
                    Contact.normalized_phone.ilike(normalized),
                )
            )

        cursor_condition = build_cursor_condition(
            sort_column=resolved_sort.column,
            id_column=Contact.id,
            sort_dir=resolved_sort.dir,
            cursor_sort_value=cursor_sort_value,
            cursor_id=cursor_id,
        )
        if cursor_condition is not None:
            conditions.append(cursor_condition)

        order_by = build_order_by(resolved_sort, Contact.id)

        stmt = (
            select(Contact)
            .where(*conditions)
            .order_by(*order_by)
            .limit(limit + 1)
        )

        result = await self.db.execute(stmt)
        return result.scalars().all(), resolved_sort

    async def search_contacts(
        self,
        *,
        business_id: UUID,
        limit: int,
        search: str | None,
        filter_group,
        sort_key: str,
        sort_dir: str,
        cursor_sort_value=None,
        cursor_id: UUID | None = None,
    ) -> tuple[Sequence[Contact], ResolvedSort, int]:
        resolved_sort = resolve_sort(
            sort_key=sort_key,
            sort_dir=sort_dir,
            sort_registry=CONTACT_SORTS,
            default_sort_key="updated_at",
        )
        conditions = [
            Contact.business_id == business_id,
            Contact.deleted_at.is_(None),
        ]

        normalized = normalize_search(search)
        if normalized:
            like = f"%{normalized}%"
            conditions.append(
                or_(
                    Contact.display_name.ilike(like),
                    Contact.normalized_phone.ilike(like),
                    Contact.email.ilike(like),
                )
            )

        filter_condition = FilterCompiler(CONTACT_FILTERS).compile(filter_group)
        if filter_condition is not None:
            conditions.append(filter_condition)

        base_stmt = select(Contact).where(*conditions)
        is_broad_query = self._is_broad_query(
            normalized_search=normalized,
            filter_group=filter_group,
        )
        total_estimate = await self._bounded_total_estimate(
            base_stmt=base_stmt,
            estimate_cap=(2000 if is_broad_query else 10000),
        )

        cursor_condition = build_cursor_condition(
            sort_column=resolved_sort.column,
            id_column=Contact.id,
            sort_dir=resolved_sort.dir,
            cursor_sort_value=cursor_sort_value,
            cursor_id=cursor_id,
        )
        stmt = base_stmt
        if cursor_condition is not None:
            stmt = stmt.where(cursor_condition)

        stmt = (
            stmt
            .order_by(*build_order_by(resolved_sort, Contact.id))
            .limit(limit + 1)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all(), resolved_sort, total_estimate

    async def _bounded_total_estimate(self, *, base_stmt, estimate_cap: int) -> int:
        # Estimate cardinality without an exact COUNT(*) on large filtered subqueries.
        estimate_ids_stmt = base_stmt.with_only_columns(Contact.id).limit(estimate_cap + 1)
        estimate_rows = (await self.db.execute(estimate_ids_stmt)).all()
        if len(estimate_rows) > estimate_cap:
            return estimate_cap
        return len(estimate_rows)

    def _is_broad_query(self, *, normalized_search: str | None, filter_group) -> bool:
        if normalized_search:
            return False
        filters = getattr(filter_group, "filters", None) or []
        return len(filters) == 0

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

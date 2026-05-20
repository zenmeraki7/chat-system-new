from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.repositories.base import TenantAppendOnlyRepository
from app.models.business_domains import WebhookEvent


class WebhookEventRepository(TenantAppendOnlyRepository[WebhookEvent]):
    def __init__(self, db: AsyncSession):
        super().__init__(WebhookEvent, db)

    async def get_by_provider_event(
        self,
        *,
        provider: str,
        event_id: str,
        business_id: UUID | None,
    ) -> WebhookEvent | None:
        del business_id
        result = await self.db.execute(
            select(WebhookEvent).where(
                WebhookEvent.provider == provider,
                WebhookEvent.event_id == event_id,
            )
        )
        return result.scalar_one_or_none()

    async def insert_once(
        self,
        *,
        provider: str,
        event_id: str,
        payload_hash: str,
        raw_payload: dict,
        business_id: UUID | None,
        processing_status: str = "pending",
    ) -> tuple[WebhookEvent, bool]:
        existing = await self.get_by_provider_event(
            provider=provider,
            event_id=event_id,
            business_id=business_id,
        )
        if existing:
            return existing, False
        try:
            async with self.db.begin_nested():
                created = await self.append(
                    business_id=business_id,
                    provider=provider,
                    event_id=event_id,
                    payload_hash=payload_hash,
                    raw_payload=raw_payload,
                    processing_status=processing_status,
                )
                return created, True
        except IntegrityError:
            pass
        existing = await self.get_by_provider_event(
            provider=provider,
            event_id=event_id,
            business_id=business_id,
        )
        if existing:
            return existing, False
        raise

    async def bulk_insert_events(self, *, rows: list[dict]) -> list[WebhookEvent]:
        if not rows:
            return []
        created: list[WebhookEvent] = []
        for row in rows:
            item, was_created = await self.insert_once(
                provider=row["provider"],
                event_id=row["event_id"],
                payload_hash=row["payload_hash"],
                raw_payload=row["raw_payload"],
                business_id=row.get("business_id"),
                processing_status=row.get("processing_status", "pending"),
            )
            if was_created:
                created.append(item)
        return created

    async def stream_for_business(self, *, business_id: UUID):
        stmt = (
            select(WebhookEvent)
            .where(
                WebhookEvent.business_id == business_id,
                WebhookEvent.deleted_at.is_(None),
            )
            .order_by(WebhookEvent.created_at.desc(), WebhookEvent.id.desc())
        )
        result = await self.db.stream(stmt)
        async for row in result.scalars():
            yield row

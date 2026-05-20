from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.repositories.base import TenantAppendOnlyRepository
from app.models.business_domains import UsageLedger


class UsageLedgerRepository(TenantAppendOnlyRepository[UsageLedger]):
    def __init__(self, db: AsyncSession):
        super().__init__(UsageLedger, db)

    async def get_by_idempotency_key(self, *, business_id: UUID, idempotency_key: str) -> UsageLedger | None:
        result = await self.db.execute(
            select(UsageLedger).where(
                UsageLedger.business_id == business_id,
                UsageLedger.idempotency_key == idempotency_key,
                UsageLedger.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def append_once(
        self,
        *,
        business_id: UUID,
        source_type: str,
        source_id: str,
        usage_type: str,
        quantity: int,
        idempotency_key: str,
        message_id: UUID | None = None,
        campaign_id: UUID | None = None,
        provider_event_id: str | None = None,
    ) -> tuple[UsageLedger, bool]:
        existing = await self.get_by_idempotency_key(
            business_id=business_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            return existing, False
        try:
            async with self.db.begin_nested():
                created = await self.append(
                    business_id=business_id,
                    source_type=source_type,
                    source_id=source_id,
                    usage_type=usage_type,
                    quantity=quantity,
                    idempotency_key=idempotency_key,
                    message_id=message_id,
                    campaign_id=campaign_id,
                    provider_event_id=provider_event_id,
                )
                return created, True
        except IntegrityError:
            pass
        existing = await self.get_by_idempotency_key(
            business_id=business_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            return existing, False
        raise

    async def bulk_append_rows(self, *, rows: list[dict]) -> list[UsageLedger]:
        if not rows:
            return []
        created: list[UsageLedger] = []
        for row in rows:
            item, was_created = await self.append_once(
                business_id=row["business_id"],
                source_type=row["source_type"],
                source_id=row["source_id"],
                usage_type=row["usage_type"],
                quantity=row["quantity"],
                idempotency_key=row["idempotency_key"],
                message_id=row.get("message_id"),
                campaign_id=row.get("campaign_id"),
                provider_event_id=row.get("provider_event_id"),
            )
            if was_created:
                created.append(item)
        return created

    async def stream_for_business(self, *, business_id: UUID):
        stmt = (
            select(UsageLedger)
            .where(
                UsageLedger.business_id == business_id,
                UsageLedger.deleted_at.is_(None),
            )
            .order_by(UsageLedger.created_at.desc(), UsageLedger.id.desc())
        )
        result = await self.db.stream(stmt)
        async for row in result.scalars():
            yield row

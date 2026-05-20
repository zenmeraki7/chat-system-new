from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.business_domains import UsageLedger
from app.repositories.usage_ledger_repo import UsageLedgerRepository


class BillingMeteringService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = UsageLedgerRepository(db)

    async def record_usage(
        self,
        business_id: UUID,
        source_type: str,
        source_id: str,
        usage_type: str,
        quantity: int,
        idempotency_key: str,
        message_id: UUID | None = None,
        campaign_id: UUID | None = None,
        provider_event_id: str | None = None,
    ) -> UsageLedger:
        row, _created = await self.repo.append_once(
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
        return row

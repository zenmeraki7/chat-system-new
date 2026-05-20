from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import OutboxEvent


async def enqueue_campaign_finalize(
    db: AsyncSession,
    *,
    business_id: UUID,
    campaign_id: UUID,
    source: str,
    debounce_seconds: int = 5,
) -> None:
    """
    Enqueue at most one pending campaign.finalize event per campaign.
    A short debounce window batches high-frequency triggers into one finalize pass.
    """
    now = datetime.now(timezone.utc)
    existing_row = await db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.event_type == "campaign.finalize",
            OutboxEvent.status == "pending",
            OutboxEvent.business_id == business_id,
            OutboxEvent.campaign_id == campaign_id,
            OutboxEvent.deleted_at.is_(None),
        )
        .order_by(OutboxEvent.created_at.desc())
        .limit(1)
    )
    if existing_row.scalar_one_or_none() is not None:
        return

    db.add(
        OutboxEvent(
            business_id=business_id,
            campaign_id=campaign_id,
            operation_id=f"campaign:{campaign_id}:finalize",
            event_type="campaign.finalize",
            payload_json={"campaign_id": str(campaign_id), "source": source},
            status="pending",
            available_at=now + timedelta(seconds=max(0, int(debounce_seconds))),
        )
    )

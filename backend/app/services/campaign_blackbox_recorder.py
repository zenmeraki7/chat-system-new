from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import CampaignExecutionEvent


class CampaignBlackBoxRecorder:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        *,
        business_id: UUID,
        campaign_id: UUID,
        event_type: str,
        message: str,
        payload_json: dict | None = None,
        observed_at: datetime | None = None,
    ) -> None:
        self.db.add(
            CampaignExecutionEvent(
                business_id=business_id,
                campaign_id=campaign_id,
                event_type=event_type.strip().lower(),
                message=message.strip(),
                payload_json=payload_json or {},
                observed_at=observed_at or datetime.now(timezone.utc),
            )
        )

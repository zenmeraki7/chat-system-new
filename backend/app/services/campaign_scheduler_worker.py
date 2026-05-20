from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.domain.status_enums import CampaignStatus
from app.models.business_domains import Campaign, CampaignStatusEvent, OutboxEvent

logger = logging.getLogger(__name__)


class CampaignSchedulerWorker:
    def __init__(self, *, poll_interval_seconds: float = 60.0, batch_size: int = 100) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self._process_due_campaigns()
                if not processed:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("campaign_scheduler_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_due_campaigns(self) -> bool:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(Campaign)
                .where(
                    Campaign.status == CampaignStatus.SCHEDULED.value,
                    Campaign.scheduled_at.is_not(None),
                    Campaign.scheduled_at <= now,
                    Campaign.deleted_at.is_(None),
                )
                .order_by(Campaign.scheduled_at.asc(), Campaign.id.asc())
                .with_for_update(skip_locked=True)
                .limit(self.batch_size)
            )
            campaigns = list(rows.scalars().all())
            if not campaigns:
                return False

            for campaign in campaigns:
                old_status = campaign.status
                campaign.status = CampaignStatus.QUEUED.value
                db.add(
                    CampaignStatusEvent(
                        campaign_id=campaign.id,
                        old_status=old_status,
                        new_status=CampaignStatus.QUEUED.value,
                        reason="campaign_scheduler_due_dispatch",
                    )
                )
                db.add(
                    OutboxEvent(
                        business_id=campaign.business_id,
                        operation_id=f"campaign:{campaign.id}",
                        event_type="campaign_dispatch_job",
                        payload_json={
                            "campaign_id": str(campaign.id),
                            "business_id": str(campaign.business_id),
                            "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
                            "dispatched_at": now.isoformat(),
                        },
                        status="pending",
                        available_at=now,
                    )
                )

            await db.commit()
            return True

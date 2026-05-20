from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.domain.status_enums import CampaignStatus
from app.models.business_domains import Campaign, CampaignStatusEvent, OutboxEvent
from app.services.campaign_blackbox_recorder import CampaignBlackBoxRecorder

logger = logging.getLogger(__name__)


class CampaignDispatchWorker:
    def __init__(self, *, poll_interval_seconds: float = 2.0, batch_size: int = 1000) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = max(500, min(5000, int(batch_size)))
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
                processed = await self._process_one()
                if not processed:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("campaign_dispatch_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "campaign_dispatch_job",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= now,
                    OutboxEvent.deleted_at.is_(None),
                )
                .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            evt = row.scalar_one_or_none()
            if evt is None:
                return False

            evt.attempts = int(evt.attempts or 0) + 1
            payload = evt.payload_json or {}
            try:
                campaign_id = UUID(str(payload["campaign_id"]))
            except Exception:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            campaign_row = await db.execute(
                select(Campaign)
                .where(
                    Campaign.id == campaign_id,
                    Campaign.deleted_at.is_(None),
                )
                .with_for_update()
            )
            campaign = campaign_row.scalar_one_or_none()
            if campaign is None:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            if campaign.cancelled_at is not None or campaign.status == CampaignStatus.CANCELLED.value:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True
            if campaign.status == CampaignStatus.PAUSED.value or campaign.paused_at is not None:
                evt.status = "pending"
                evt.available_at = now + timedelta(seconds=30)
                await db.commit()
                return True
            if campaign.status != CampaignStatus.QUEUED.value:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            db.add(
                OutboxEvent(
                    business_id=campaign.business_id,
                    campaign_id=campaign.id,
                    operation_id=f"campaign:{campaign.id}:batch:0",
                    event_type="campaign_batch_dispatch_job",
                    payload_json={
                        "campaign_id": str(campaign.id),
                        "business_id": str(campaign.business_id),
                        "batch_size": self.batch_size,
                        "cursor_after_recipient_id": None,
                    },
                    status="pending",
                    available_at=now,
                )
            )
            await CampaignBlackBoxRecorder(db).record(
                business_id=campaign.business_id,
                campaign_id=campaign.id,
                event_type="dispatch_batch_created",
                message="Dispatch batch #1 created",
                payload_json={"batch_size": self.batch_size, "cursor_after_recipient_id": None},
            )

            campaign.status = CampaignStatus.RUNNING.value
            if campaign.started_at is None:
                campaign.started_at = now
            db.add(
                CampaignStatusEvent(
                    campaign_id=campaign.id,
                    old_status=CampaignStatus.QUEUED.value,
                    new_status=CampaignStatus.RUNNING.value,
                    reason="campaign_dispatch_started",
                )
            )
            evt.status = "processed"
            evt.processed_at = now
            await db.commit()
            return True

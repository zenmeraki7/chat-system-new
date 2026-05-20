from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.domain.status_enums import CampaignStatus
from app.models.business_domains import Campaign
from app.services.campaign_finalize_enqueue_service import enqueue_campaign_finalize

logger = logging.getLogger(__name__)


class CampaignFinalizeSweeperWorker:
    def __init__(self, *, run_interval_seconds: float = 30.0, campaign_batch_size: int = 100) -> None:
        self.run_interval_seconds = run_interval_seconds
        self.campaign_batch_size = campaign_batch_size
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
                await self._sweep_once()
            except Exception:
                logger.exception("campaign_finalize_sweeper_worker_failed")
            await asyncio.sleep(self.run_interval_seconds)

    async def _sweep_once(self) -> None:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(Campaign)
                .where(
                    Campaign.deleted_at.is_(None),
                    Campaign.status.in_(
                        [
                            CampaignStatus.SCHEDULED.value,
                            CampaignStatus.QUEUED.value,
                            CampaignStatus.RUNNING.value,
                            CampaignStatus.PAUSED.value,
                        ]
                    ),
                )
                .order_by(Campaign.updated_at.desc(), Campaign.id.asc())
                .limit(self.campaign_batch_size)
            )
            campaigns = list(rows.scalars().all())
            for campaign in campaigns:
                await enqueue_campaign_finalize(
                    db,
                    business_id=campaign.business_id,
                    campaign_id=campaign.id,
                    source="periodic_sweep",
                    debounce_seconds=5,
                )
            await db.commit()

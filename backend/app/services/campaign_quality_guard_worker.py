from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import Campaign
from app.services.campaign_quality_guard_service import CampaignQualityGuardService

logger = logging.getLogger(__name__)


class CampaignQualityGuardWorker:
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
                await self._process_batch()
            except Exception:
                logger.exception("campaign_quality_guard_worker_failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _process_batch(self) -> None:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(Campaign)
                .where(
                    Campaign.deleted_at.is_(None),
                    Campaign.status.in_(["running", "queued", "scheduled"]),
                )
                .order_by(Campaign.updated_at.desc(), Campaign.id.asc())
                .limit(self.batch_size)
            )
            campaigns = list(rows.scalars().all())
            if not campaigns:
                return
            guard = CampaignQualityGuardService(db)
            for campaign in campaigns:
                await guard.evaluate_and_apply(campaign=campaign)
            await db.commit()


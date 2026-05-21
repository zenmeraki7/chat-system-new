from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.business_domains import Campaign, CampaignRecipient
from app.services.degradation_mode_service import should_defer_domain

logger = logging.getLogger(__name__)


class CampaignAnalyticsReconcileWorker:
    def __init__(self, *, run_interval_seconds: float = 300.0, campaign_batch_size: int = 100) -> None:
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
            if should_defer_domain("analytics"):
                await asyncio.sleep(self.run_interval_seconds)
                continue
            try:
                await self._reconcile_batch()
            except Exception:
                logger.exception("campaign_analytics_reconcile_worker_failed")
            await asyncio.sleep(self.run_interval_seconds)

    async def _reconcile_batch(self) -> None:
        now = datetime.now(timezone.utc)
        # Prefer active/recent campaigns; older completed campaigns are lower drift-risk.
        recent_cutoff = now - timedelta(days=30)
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(Campaign)
                .where(
                    Campaign.deleted_at.is_(None),
                    (
                        Campaign.status.in_(["scheduled", "queued", "running", "paused"])
                        | (Campaign.updated_at >= recent_cutoff)
                    ),
                )
                .order_by(Campaign.updated_at.desc(), Campaign.id.asc())
                .limit(self.campaign_batch_size)
            )
            campaigns = list(rows.scalars().all())
            if not campaigns:
                return

            for campaign in campaigns:
                counts = await db.execute(
                    select(
                        func.count(CampaignRecipient.id),
                        func.sum(func.case((CampaignRecipient.status == "sent", 1), else_=0)),
                        func.sum(func.case((CampaignRecipient.status == "delivered", 1), else_=0)),
                        func.sum(func.case((CampaignRecipient.status == "read", 1), else_=0)),
                        func.sum(func.case((CampaignRecipient.status == "replied", 1), else_=0)),
                        func.sum(func.case((CampaignRecipient.status == "failed", 1), else_=0)),
                        func.sum(func.case((CampaignRecipient.status == "skipped", 1), else_=0)),
                        func.sum(func.coalesce(CampaignRecipient.actual_cost, 0.0)),
                    ).where(
                        CampaignRecipient.campaign_id == campaign.id,
                        CampaignRecipient.deleted_at.is_(None),
                    )
                )
                (
                    total_count,
                    sent_count,
                    delivered_count,
                    read_count,
                    replied_count,
                    failed_count,
                    skipped_count,
                    actual_cost,
                ) = counts.one()

                campaign.total_recipients = int(total_count or 0)
                campaign.sent_count = int(sent_count or 0)
                campaign.delivered_count = int(delivered_count or 0)
                campaign.read_count = int(read_count or 0)
                campaign.replied_count = int(replied_count or 0)
                campaign.failed_count = int(failed_count or 0)
                campaign.skipped_recipients = int(skipped_count or 0)
                campaign.actual_cost = float(actual_cost or 0.0)

            await db.commit()

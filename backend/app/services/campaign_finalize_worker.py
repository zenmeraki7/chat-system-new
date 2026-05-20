from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.domain.status_enums import CampaignStatus
from app.models.business_domains import Campaign, CampaignStatusEvent, CampaignRecipient, OutboxEvent

logger = logging.getLogger(__name__)


class CampaignFinalizeWorker:
    def __init__(
        self,
        *,
        poll_interval_seconds: float = 2.0,
        max_batch_size: int = 20,
        max_parallelism: int = 4,
    ) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.max_batch_size = max(1, int(max_batch_size))
        self.max_parallelism = max(1, int(max_parallelism))
        self._last_parallelism = self.max_parallelism
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
                processed = await self._process_batch_tick()
                if processed == 0:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("campaign_finalize_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_batch_tick(self) -> int:
        processed = 0
        remaining = self.max_batch_size
        dynamic_parallelism = await self._resolve_parallelism()
        while remaining > 0 and not self._stop.is_set():
            wave = min(dynamic_parallelism, remaining)
            results = await asyncio.gather(*[self._process_one() for _ in range(wave)], return_exceptions=True)
            wave_processed = 0
            for result in results:
                if isinstance(result, Exception):
                    logger.exception("campaign_finalize_worker_batch_item_failed", exc_info=result)
                    continue
                if result:
                    wave_processed += 1
            processed += wave_processed
            if wave_processed == 0:
                break
            remaining -= wave
        return processed

    async def _resolve_parallelism(self) -> int:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            pending_q = await db.execute(
                select(OutboxEvent.id)
                .where(
                    OutboxEvent.event_type == "campaign.finalize",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= now,
                    OutboxEvent.deleted_at.is_(None),
                )
                .limit(200)
            )
            depth = len(list(pending_q.scalars().all()))
        if depth >= 100:
            self._last_parallelism = self.max_parallelism
        elif depth >= 30:
            self._last_parallelism = max(2, min(self.max_parallelism, self.max_parallelism // 2))
        else:
            self._last_parallelism = 1
        return self._last_parallelism

    async def _process_one(self) -> bool:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "campaign.finalize",
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

            campaign_id = evt.campaign_id
            if campaign_id is None:
                payload = evt.payload_json or {}
                campaign_id_raw = payload.get("campaign_id")
                campaign_id = UUID(str(campaign_id_raw)) if campaign_id_raw else None
            if campaign_id is None:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            campaign = (
                await db.execute(
                    select(Campaign).where(Campaign.id == campaign_id, Campaign.deleted_at.is_(None)).with_for_update()
                )
            ).scalar_one_or_none()
            if campaign is None:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            if campaign.status in {
                CampaignStatus.CANCELLED.value,
                CampaignStatus.COMPLETED.value,
                CampaignStatus.COMPLETED_WITH_FAILURES.value,
                CampaignStatus.FAILED.value,
            }:
                evt.status = "processed"
                evt.processed_at = now
                await db.commit()
                return True

            active_count_q = await db.execute(
                select(
                    func.count(CampaignRecipient.id)
                ).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.status.in_(["pending", "eligible", "reserved", "queued", "sending", "unknown_retryable"]),
                )
            )
            active_count = int(active_count_q.scalar_one() or 0)
            if active_count > 0:
                evt.status = "processed"
                evt.processed_at = now
                await db.commit()
                return True

            final_counts_q = await db.execute(
                select(
                    func.sum(func.case((CampaignRecipient.status == "failed", 1), else_=0)),
                    func.sum(func.case((CampaignRecipient.status == "skipped", 1), else_=0)),
                ).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                )
            )
            failed_i, skipped_i = final_counts_q.one()
            failed_i = int(failed_i or 0)
            skipped_i = int(skipped_i or 0)

            old = campaign.status
            campaign.status = (
                CampaignStatus.COMPLETED_WITH_FAILURES.value
                if (failed_i > 0 or skipped_i > 0)
                else CampaignStatus.COMPLETED.value
            )
            campaign.completed_at = now
            db.add(
                CampaignStatusEvent(
                    campaign_id=campaign.id,
                    old_status=old,
                    new_status=campaign.status,
                    reason="finalized_by_worker",
                )
            )

            evt.status = "processed"
            evt.processed_at = now
            await db.commit()
            return True

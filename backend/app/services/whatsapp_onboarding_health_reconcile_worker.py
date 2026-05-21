from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import WhatsAppIntegration
from app.services.whatsapp_onboarding_health_projector import WhatsAppOnboardingHealthProjector

logger = logging.getLogger(__name__)


class WhatsAppOnboardingHealthReconcileWorker:
    def __init__(self, *, poll_interval_seconds: float = 120.0, max_batch_size: int = 100) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.max_batch_size = max(1, int(max_batch_size))
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
                await self._reconcile_once()
            except Exception:
                logger.exception("whatsapp_onboarding_health_reconcile_worker_loop_failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _reconcile_once(self) -> None:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(WhatsAppIntegration.business_id)
                .where(WhatsAppIntegration.deleted_at.is_(None))
                .order_by(WhatsAppIntegration.created_at.asc())
                .limit(self.max_batch_size)
            )
            for business_id in rows.scalars().all():
                try:
                    await WhatsAppOnboardingHealthProjector(db).project_and_apply(
                        business_id=business_id,
                        actor_user_id=None,
                        trigger="health_reconcile_worker",
                    )
                except Exception:
                    logger.exception("whatsapp_onboarding_health_projection_failed", extra={"business_id": str(business_id)})
            await db.commit()

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import WhatsAppBusinessAccount, WhatsAppIntegration
from app.services.template_graph_sync_service import TemplateGraphSyncService

logger = logging.getLogger(__name__)


class TemplateSyncReconcileWorker:
    def __init__(
        self,
        *,
        poll_interval_seconds: float = 600.0,
        max_batch_size: int = 25,
        stale_after_minutes: int = 30,
    ) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.max_batch_size = max(1, int(max_batch_size))
        self.stale_after_minutes = max(5, int(stale_after_minutes))
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
                logger.exception("template_sync_reconcile_worker_loop_failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _reconcile_once(self) -> None:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=self.stale_after_minutes)
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(WhatsAppBusinessAccount, WhatsAppIntegration)
                .join(WhatsAppIntegration, WhatsAppIntegration.business_id == WhatsAppBusinessAccount.business_id)
                .where(
                    WhatsAppBusinessAccount.deleted_at.is_(None),
                    WhatsAppIntegration.deleted_at.is_(None),
                    WhatsAppIntegration.status.in_(["connected", "provisioning"]),
                    (
                        (WhatsAppBusinessAccount.last_template_sync_at.is_(None))
                        | (WhatsAppBusinessAccount.last_template_sync_at < threshold)
                    ),
                )
                .order_by(WhatsAppBusinessAccount.created_at.asc())
                .limit(self.max_batch_size)
            )
            pairs = rows.all()
            seen_businesses: set[str] = set()
            for waba, _integration in pairs:
                business_key = str(waba.business_id)
                if business_key in seen_businesses:
                    continue
                seen_businesses.add(business_key)
                try:
                    await TemplateGraphSyncService(db).sync_business_templates(
                        business_id=waba.business_id,
                        requested_by_user_id=None,
                        trigger="reconcile_worker",
                    )
                except Exception:
                    logger.exception("template_sync_reconcile_business_failed", extra={"business_id": str(waba.business_id)})

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import OutboxEvent
from app.services.contact_import_service import ContactImportService

logger = logging.getLogger(__name__)


class ContactImportWorker:
    def __init__(self, *, poll_interval_seconds: float = 1.0) -> None:
        self.poll_interval_seconds = poll_interval_seconds
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
                logger.exception("contact_import_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "contact_import.process_csv",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= datetime.now(timezone.utc),
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
            job_id_raw = payload.get("import_job_id")
            if not job_id_raw:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True
            try:
                job_id = UUID(str(job_id_raw))
            except Exception:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            try:
                await ContactImportService(db).process_import_job(job_id)
                evt.status = "processed"
                evt.processed_at = datetime.now(timezone.utc)
            except Exception as exc:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                evt.payload_json = {**payload, "worker_error": str(exc)}
            await db.commit()
            return True

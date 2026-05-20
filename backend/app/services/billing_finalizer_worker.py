from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import BillingLedger, OutboxEvent

logger = logging.getLogger(__name__)


class BillingFinalizerWorker:
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
                logger.exception("billing_finalizer_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "billing.finalize",
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

            payload = evt.payload_json or {}
            business_id = payload.get("business_id")
            entry_type = payload.get("entry_type")
            amount = float(payload.get("amount") or 0.0)
            currency = str(payload.get("currency") or "USD")
            if not business_id or not entry_type:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            db.add(
                BillingLedger(
                    business_id=UUID(str(business_id)),
                    campaign_id=UUID(str(payload["campaign_id"])) if payload.get("campaign_id") else None,
                    campaign_recipient_id=UUID(str(payload["campaign_recipient_id"])) if payload.get("campaign_recipient_id") else None,
                    message_outbox_id=UUID(str(payload["message_outbox_id"])) if payload.get("message_outbox_id") else None,
                    provider_message_id=payload.get("provider_message_id"),
                    entry_type=str(entry_type),
                    amount=amount,
                    currency=currency,
                    status=str(payload.get("status") or "posted"),
                    reason=str(payload.get("reason") or "finalized"),
                    metadata_json=payload.get("metadata_json") or {},
                )
            )
            evt.status = "processed"
            evt.processed_at = now
            await db.commit()
            return True


from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import OutboxEvent
from app.repositories.message_repo import MessageRepository
from app.services.message_outbox_enqueue_service import MessageOutboxEnqueueService

logger = logging.getLogger(__name__)


class OutboundSendWorker:
    """
    Universal outbox bridge:
    Converts legacy outbound send events into message_outbox rows.
    Provider calls are handled only by message_send_worker.
    """

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
                logger.exception("outbound_send_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "whatsapp.send.outbound",
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
            try:
                business_id = UUID(payload["business_id"])
                message_id = UUID(payload["message_id"])
                to = str(payload["to"])
                text = str(payload["text"])
                phone_number_id = str(payload["phone_number_id"])
                source = str(payload.get("source") or "api_trigger")
            except Exception:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            msg = await MessageRepository(db).get_for_update(business_id=business_id, message_id=message_id)
            if msg is None:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            outbox = await MessageOutboxEnqueueService(db).enqueue_text(
                business_id=business_id,
                phone_number_id=phone_number_id,
                to_phone_e164=to,
                text=text,
                idempotency_key=f"message:{message_id}",
                source=source,
                priority=80,
                conversation_id=msg.conversation_id,
                extra_payload={"legacy_message_id": str(message_id)},
            )
            msg.status = "queued"
            msg.provider_payload = {"message_outbox_id": str(outbox.id), "source": "universal_outbox"}
            evt.status = "processed"
            evt.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return True

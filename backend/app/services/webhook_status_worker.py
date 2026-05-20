from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import (
    CampaignRecipient,
    CampaignRecipientEvent,
    MessageOutbox,
    MessageStatusEvent,
    OutboundMessage,
    OutboxEvent,
)
from app.services.campaign_finalize_enqueue_service import enqueue_campaign_finalize

logger = logging.getLogger(__name__)

_STATUS_RANK = {
    "accepted": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
}


class WebhookStatusWorker:
    def __init__(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        max_batch_size: int = 30,
        max_parallelism: int = 8,
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
                logger.exception("webhook_status_worker_loop_failed")
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
                    logger.exception("webhook_status_worker_batch_item_failed", exc_info=result)
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
                    OutboxEvent.event_type == "webhook.status.whatsapp",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= now,
                    OutboxEvent.deleted_at.is_(None),
                )
                .limit(200)
            )
            depth = len(list(pending_q.scalars().all()))
        if depth >= 100:
            self._last_parallelism = self.max_parallelism
        elif depth >= 40:
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
                    OutboxEvent.event_type == "webhook.status.whatsapp",
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
            provider_message_id = str(payload.get("provider_message_id") or "")
            incoming_status = str(payload.get("status") or "").lower()
            if not provider_message_id or not incoming_status:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            outbox_row = await db.execute(
                select(MessageOutbox)
                .where(
                    MessageOutbox.provider_message_id == provider_message_id,
                    MessageOutbox.deleted_at.is_(None),
                )
                .order_by(MessageOutbox.created_at.desc())
                .with_for_update()
                .limit(1)
            )
            outbox = outbox_row.scalar_one_or_none()
            if outbox is None:
                evt.status = "processed"
                evt.processed_at = now
                await db.commit()
                return True

            recipient: CampaignRecipient | None = None
            if outbox.campaign_recipient_id is not None:
                recipient = (
                    await db.execute(
                        select(CampaignRecipient)
                        .where(CampaignRecipient.id == outbox.campaign_recipient_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
            provider_ts = None
            try:
                ts = payload.get("timestamp")
                if ts:
                    provider_ts = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                provider_ts = None

            provider_event_id = str(payload.get("provider_event_id") or "").strip()
            dedupe_found = False
            if provider_event_id:
                dedupe_evt_id = await db.execute(
                    select(MessageStatusEvent.id).where(
                        MessageStatusEvent.provider_event_id == provider_event_id,
                        MessageStatusEvent.deleted_at.is_(None),
                    ).limit(1)
                )
                dedupe_found = dedupe_evt_id.scalar_one_or_none() is not None
            if not dedupe_found:
                dedupe = await db.execute(
                    select(MessageStatusEvent.id).where(
                        MessageStatusEvent.provider_message_id == provider_message_id,
                        MessageStatusEvent.status == incoming_status,
                        MessageStatusEvent.timestamp == provider_ts,
                        MessageStatusEvent.deleted_at.is_(None),
                    ).limit(1)
                )
                dedupe_found = dedupe.scalar_one_or_none() is not None

            if not dedupe_found:
                await self._ensure_outbound_message_shadow(db, outbox)
                db.add(
                    MessageStatusEvent(
                        business_id=outbox.business_id,
                        outbound_message_id=outbox.id,
                        message_id=None,
                        provider_event_id=provider_event_id or provider_message_id,
                        provider_status=incoming_status,
                        provider_timestamp=provider_ts,
                        raw_payload_json=payload.get("raw_payload"),
                        received_webhook_event_id=None,
                        status=incoming_status,
                        phone_number_id=outbox.phone_number_id,
                        provider_message_id=provider_message_id,
                        timestamp=provider_ts,
                        pricing_json=payload.get("pricing"),
                        conversation_json=payload.get("conversation"),
                        errors_json=payload.get("errors"),
                        payload=payload,
                    )
                )

            await self._apply_monotonic_update(
                db=db,
                outbox=outbox,
                recipient=recipient,
                incoming_status=incoming_status,
                provider_message_id=provider_message_id,
                provider_ts=provider_ts,
                payload=payload,
            )
            if outbox.campaign_id is not None:
                await enqueue_campaign_finalize(
                    db,
                    business_id=outbox.business_id,
                    campaign_id=outbox.campaign_id,
                    source="webhook_status",
                    debounce_seconds=5,
                )

            evt.status = "processed"
            evt.processed_at = now
            await db.commit()
            return True

    async def _ensure_outbound_message_shadow(self, db, outbox: MessageOutbox) -> None:
        existing = await db.execute(select(OutboundMessage).where(OutboundMessage.id == outbox.id))
        if existing.scalar_one_or_none() is not None:
            return
        db.add(
            OutboundMessage(
                id=outbox.id,
                business_id=outbox.business_id,
                phone_number_id=outbox.phone_number_id,
                contact_id=outbox.to_phone_e164,
                idempotency_key=outbox.idempotency_key,
                payload=outbox.payload_json or {},
                status=outbox.status,
                environment="live",
            )
        )

    async def _apply_monotonic_update(
        self,
        *,
        db,
        outbox: MessageOutbox,
        recipient: CampaignRecipient | None,
        incoming_status: str,
        provider_message_id: str,
        provider_ts: datetime | None,
        payload: dict,
    ) -> None:
        current = (recipient.status if recipient is not None else outbox.status or "").lower()

        # Late failure should not downgrade delivered/read unless payload clearly says final failure.
        if incoming_status == "failed":
            final_failure = bool((payload.get("errors") or [])) or bool((payload.get("conversation") or {}).get("origin"))
            if current in {"read", "delivered"} and not final_failure:
                return
            outbox.status = "failed"
            outbox.error_code = str((((payload.get("errors") or [{}])[0] or {}).get("code")) or "failed")
            outbox.error_message = str((((payload.get("errors") or [{}])[0] or {}).get("title")) or "provider_failed")
            if recipient is not None and recipient.status not in {"read", "delivered"}:
                prev = recipient.status
                recipient.status = "failed"
                recipient.failed_at = provider_ts or datetime.now(timezone.utc)
                recipient.provider_message_id = provider_message_id
                recipient.last_error_code = outbox.error_code
                recipient.last_error_message = outbox.error_message
                db.add(
                    CampaignRecipientEvent(
                        campaign_id=recipient.campaign_id,
                        campaign_recipient_id=recipient.id,
                        business_id=recipient.business_id,
                        event_type="campaign_recipient.failed_from_webhook",
                        old_status=prev,
                        new_status="failed",
                        provider_message_id=provider_message_id,
                        payload_json=payload,
                        error_code=recipient.last_error_code,
                        error_message=recipient.last_error_message,
                    )
                )
                db.add(
                    OutboxEvent(
                        business_id=outbox.business_id,
                        operation_id=f"billing:{outbox.id}:failed",
                        event_type="billing.finalize",
                        payload_json={
                            "business_id": str(outbox.business_id),
                            "campaign_id": str(outbox.campaign_id) if outbox.campaign_id else None,
                            "campaign_recipient_id": str(outbox.campaign_recipient_id) if outbox.campaign_recipient_id else None,
                            "message_outbox_id": str(outbox.id),
                            "provider_message_id": provider_message_id,
                            "entry_type": "release",
                            "amount": 0,
                            "currency": "USD",
                            "status": "posted",
                            "reason": "failed_webhook",
                            "metadata_json": {"status": "failed"},
                        },
                        status="pending",
                    )
                )
            return

        target_rank = _STATUS_RANK.get(incoming_status)
        if target_rank is None:
            return
        current_rank = _STATUS_RANK.get(current, 0)
        if target_rank < current_rank:
            return

        outbox.status = "sent" if incoming_status in {"accepted", "sent", "delivered", "read"} else outbox.status
        outbox.provider_message_id = provider_message_id

        if recipient is None:
            return

        prev = recipient.status
        new_status = prev
        if incoming_status in {"accepted", "sent"}:
            new_status = "sent"
            recipient.sent_at = provider_ts or recipient.sent_at or datetime.now(timezone.utc)
        elif incoming_status == "delivered":
            new_status = "delivered"
            recipient.delivered_at = provider_ts or datetime.now(timezone.utc)
        elif incoming_status == "read":
            new_status = "read"
            recipient.read_at = provider_ts or datetime.now(timezone.utc)

        if new_status != prev:
            recipient.status = new_status
            recipient.provider_message_id = provider_message_id
            db.add(
                CampaignRecipientEvent(
                    campaign_id=recipient.campaign_id,
                    campaign_recipient_id=recipient.id,
                    business_id=recipient.business_id,
                    event_type="campaign_recipient.status_from_webhook",
                    old_status=prev,
                    new_status=new_status,
                    provider_message_id=provider_message_id,
                    payload_json=payload,
                )
            )
            db.add(
                OutboxEvent(
                    business_id=outbox.business_id,
                    operation_id=f"billing:{outbox.id}:{new_status}",
                    event_type="billing.finalize",
                    payload_json={
                        "business_id": str(outbox.business_id),
                        "campaign_id": str(outbox.campaign_id) if outbox.campaign_id else None,
                        "campaign_recipient_id": str(outbox.campaign_recipient_id) if outbox.campaign_recipient_id else None,
                        "message_outbox_id": str(outbox.id),
                        "provider_message_id": provider_message_id,
                        "entry_type": "capture" if new_status in {"sent", "delivered", "read"} else "adjustment",
                        "amount": 0,
                        "currency": "USD",
                        "status": "posted",
                        "reason": f"webhook_status_{new_status}",
                        "metadata_json": {"status": new_status},
                    },
                    status="pending",
                )
            )

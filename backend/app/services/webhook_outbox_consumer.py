import asyncio
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business import Business
from app.models.business_domains import (
    OutboxEvent,
    WebhookEvent,
    WebhookProcessingAttempt,
    WebhookDeadLetter,
    WhatsAppPhoneNumber,
    WhatsAppBusinessAccount,
    ProviderWebhookEvent,
)
from app.services.chat_service import ChatService
from app.services.audit_log_service import AuditLogService
from app.services.queue_routing_service import classify_outbox_event, worker_region_normalized
from app.services.webhook_tenant_resolver import WebhookTenantResolver
from app.repositories.contact_repo import ContactRepository
from app.models.business_domains import Contact, SuppressionListEntry

logger = logging.getLogger(__name__)
_STOP_KEYWORDS = {"stop", "unsubscribe", "optout", "quit", "cancel"}


class WebhookOutboxConsumer:
    def __init__(self, *, poll_interval_seconds: float = 2.0, max_attempts: int = 5) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.max_attempts = max_attempts
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
                processed_any = await self._process_one()
                if not processed_any:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("webhook_outbox_consumer_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        region = worker_region_normalized()
        async with AsyncSessionLocal() as db:
            region_clause = True if region == "global" else OutboxEvent.queue_region.in_(["global", region, region.upper()])
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "webhook.process.whatsapp",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= datetime.now(timezone.utc),
                    OutboxEvent.deleted_at.is_(None),
                    region_clause,
                )
                .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            event = row.scalar_one_or_none()
            if not event:
                return False

            event.attempts = int(event.attempts or 0) + 1
            webhook_event_id_raw = event.payload_json.get("webhook_event_id")
            if not webhook_event_id_raw:
                event.status = "failed"
                event.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            try:
                webhook_event_id = UUID(webhook_event_id_raw)
            except ValueError:
                event.status = "failed"
                event.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            webhook_result = await db.execute(
                select(WebhookEvent).where(WebhookEvent.id == webhook_event_id).with_for_update()
            )
            webhook_event = webhook_result.scalar_one_or_none()
            if webhook_event is None:
                event.status = "failed"
                event.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            try:
                if webhook_event.business_id is None:
                    resolved = await self._resolve_tenant_from_payload(db, webhook_event.raw_payload or {})
                    if resolved is not None:
                        webhook_event.business_id = resolved
                await self._process_whatsapp_webhook(db, webhook_event)
                webhook_event.processing_status = "processed"
                webhook_event.processed_at = datetime.now(timezone.utc)
                await self._mark_provider_event_status(db, webhook_event.event_id, "processed", None)
                event.status = "processed"
                event.processed_at = datetime.now(timezone.utc)
                db.add(WebhookProcessingAttempt(webhook_event_id=webhook_event.id, status="processed"))
                if webhook_event.business_id:
                    await AuditLogService(db).write(
                        action="whatsapp.webhook.process",
                        resource_type="webhook_event",
                        business_id=webhook_event.business_id,
                        actor_type="system",
                        status="success",
                        resource_id=str(webhook_event.id),
                        details={"provider_event_id": webhook_event.event_id},
                    )
            except Exception as exc:
                webhook_event.processing_status = "failed"
                webhook_event.failure_reason = str(exc)
                await self._mark_provider_event_status(db, webhook_event.event_id, "failed", str(exc))
                db.add(WebhookProcessingAttempt(webhook_event_id=webhook_event.id, status="failed", failure_reason=str(exc)))
                if event.attempts >= self.max_attempts:
                    event.status = "failed"
                    event.processed_at = datetime.now(timezone.utc)
                    db.add(WebhookDeadLetter(webhook_event_id=webhook_event.id, reason=str(exc)))
                else:
                    event.status = "pending"
                    # Exponential backoff with 2^attempt seconds (max 5 min).
                    backoff_seconds = min(300, 2 ** int(event.attempts))
                    event.available_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
                logger.exception("webhook_outbox_process_failed")
            await db.commit()
            return True

    async def _process_whatsapp_webhook(self, db, webhook_event: WebhookEvent) -> None:
        payload = webhook_event.raw_payload or {}
        business_id = webhook_event.business_id
        if business_id is None:
            raise ValueError("Webhook event cannot be processed without resolved business_id")
        region = (
            await db.execute(select(Business.data_region).where(Business.id == business_id).limit(1))
        ).scalar_one_or_none()
        queue_region = str(region or "global")
        status_queue_domain, status_workload_class = classify_outbox_event("webhook.status.whatsapp")
        suppression_queue_domain, suppression_workload_class = classify_outbox_event("contact.suppression.history")

        for entry in payload.get("entry", []):
            entry_waba_id = entry.get("id")
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                metadata = value.get("metadata") or {}
                phone_number_id = metadata.get("phone_number_id")
                # Incoming messages
                for message in value.get("messages", []):
                    from_wa_id = (message or {}).get("from")
                    text_body = ((message or {}).get("text") or {}).get("body")
                    message_id = (message or {}).get("id")
                    if not from_wa_id or not text_body:
                        continue
                    await self._apply_stop_unsubscribe_if_needed(
                        db=db,
                        business_id=business_id,
                        from_wa_id=str(from_wa_id),
                        text_body=str(text_body),
                    )
                    await ChatService(db).handle_incoming_message(
                        api_key="",
                        visitor_id=from_wa_id,
                        user_content=text_body,
                        business_id=business_id,
                        channel="whatsapp",
                        phone_number_id=phone_number_id,
                    )
                # Outgoing/incoming message lifecycle statuses
                for status in value.get("statuses", []):
                    provider_message_id = (status or {}).get("id")
                    provider_status = ((status or {}).get("status") or "").lower()
                    provider_event_id = f"{webhook_event.event_id}:{provider_message_id}:{provider_status}"
                    if not provider_message_id or not provider_status:
                        continue
                    db.add(
                        OutboxEvent(
                            business_id=business_id,
                            operation_id=provider_event_id,
                            event_type="webhook.status.whatsapp",
                            queue_region=queue_region,
                            queue_domain=status_queue_domain,
                            workload_class=status_workload_class,
                            payload_json={
                                "webhook_event_id": str(webhook_event.id),
                                "provider_event_id": provider_event_id,
                                "provider_message_id": provider_message_id,
                                "status": provider_status,
                                "timestamp": (status or {}).get("timestamp"),
                                "pricing": (status or {}).get("pricing"),
                                "conversation": (status or {}).get("conversation"),
                                "errors": (status or {}).get("errors"),
                                "phone_number_id": phone_number_id,
                                "raw_payload": status,
                            },
                            status="pending",
                        )
                    )
                    await self._audit_platform_event(
                        db,
                        business_id,
                        webhook_event.id,
                        "message_status_enqueued",
                        {
                            "provider_event_id": provider_event_id,
                            "provider_message_id": provider_message_id,
                            "status": provider_status,
                            "provider_timestamp": (status or {}).get("timestamp"),
                        },
                    )
                # Template status and quality/phone changes
                for update_evt in value.get("message_template_status_update", []) if isinstance(value.get("message_template_status_update"), list) else []:
                    await self._audit_platform_event(
                        db,
                        business_id,
                        webhook_event.id,
                        "template_status_update",
                        update_evt,
                    )
                if value.get("event"):
                    await self._audit_platform_event(
                        db,
                        business_id,
                        webhook_event.id,
                        "platform_event",
                        value,
                    )
                # Refresh phone/WABA profile freshness markers on any related event.
                if phone_number_id:
                    await db.execute(
                        select(WhatsAppPhoneNumber)
                        .where(
                            WhatsAppPhoneNumber.business_id == business_id,
                            WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                        )
                        .with_for_update()
                    )
                if entry_waba_id:
                    await db.execute(
                        select(WhatsAppBusinessAccount)
                        .where(
                            WhatsAppBusinessAccount.business_id == business_id,
                            WhatsAppBusinessAccount.waba_id == entry_waba_id,
                        )
                        .with_for_update()
                    )

    async def _resolve_tenant_from_payload(self, db, payload: dict) -> UUID | None:
        for entry in payload.get("entry", []):
            waba_id = entry.get("id")
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
                if not waba_id or not phone_number_id:
                    continue
                try:
                    business, _ = await WebhookTenantResolver(db).resolve(waba_id=waba_id, phone_number_id=phone_number_id)
                    return business.id
                except Exception as exc:
                    logger.warning(
                        "webhook_outbox_tenant_resolution_failed waba_id=%s phone_number_id=%s error=%s",
                        str(waba_id),
                        str(phone_number_id),
                        str(exc),
                    )
                    continue
        return None

    async def _mark_provider_event_status(self, db, event_id: str, status: str, failure_reason: str | None) -> None:
        row = await db.execute(
            select(ProviderWebhookEvent)
            .where(ProviderWebhookEvent.event_id == event_id)
            .order_by(ProviderWebhookEvent.created_at.desc())
            .with_for_update()
        )
        evt = row.scalars().first()
        if evt is None:
            return
        evt.processing_status = status
        evt.processed_at = datetime.now(timezone.utc)
        evt.failure_reason = failure_reason

    async def _apply_stop_unsubscribe_if_needed(self, *, db, business_id: UUID, from_wa_id: str, text_body: str) -> None:
        token = (text_body or "").strip().lower()
        if token not in _STOP_KEYWORDS:
            return
        contact = (
            await db.execute(
                select(Contact).where(
                    Contact.business_id == business_id,
                    Contact.wa_id == from_wa_id,
                    Contact.deleted_at.is_(None),
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if contact is None:
            return
        await ContactRepository(db).set_opt_in(
            business_id=business_id,
            contact_id=contact.id,
            status="unsubscribed",
            source="stop_keyword",
        )
        if contact.normalized_phone:
            db.add(
                SuppressionListEntry(
                    business_id=business_id,
                    channel_type="whatsapp",
                    identity_hash=contact.phone_hash or contact.normalized_phone,
                    reason="OPTED_OUT",
                    source="stop_keyword",
                )
            )
        region = (
            await db.execute(select(Business.data_region).where(Business.id == business_id).limit(1))
        ).scalar_one_or_none()
        queue_region = str(region or "global")
        suppression_queue_domain, suppression_workload_class = classify_outbox_event("contact.suppression.history")
        db.add(
            OutboxEvent(
                business_id=business_id,
                event_type="contact.suppression.history",
                queue_region=queue_region,
                queue_domain=suppression_queue_domain,
                workload_class=suppression_workload_class,
                payload_json={
                    "contact_id": str(contact.id),
                    "wa_id": from_wa_id,
                    "reason": "OPTED_OUT",
                    "source": "stop_keyword",
                    "message_text": text_body[:120],
                },
                status="pending",
            )
        )

    async def _audit_platform_event(self, db, business_id: UUID, webhook_event_id: UUID, kind: str, payload: dict) -> None:
        await AuditLogService(db).write(
            action=f"whatsapp.webhook.{kind}",
            resource_type="webhook_event",
            business_id=business_id,
            actor_type="system",
            status="success",
            resource_id=str(webhook_event_id),
            details={"payload": payload},
        )

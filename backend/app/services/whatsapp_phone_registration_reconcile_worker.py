from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import OutboxEvent, WhatsAppIntegration, WhatsAppPhoneNumber
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class WhatsAppPhoneRegistrationReconcileWorker:
    def __init__(self, *, poll_interval_seconds: float = 300.0, max_batch_size: int = 100) -> None:
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
                logger.exception("whatsapp_phone_registration_reconcile_loop_failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _reconcile_once(self) -> None:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(WhatsAppPhoneNumber, WhatsAppIntegration)
                .join(
                    WhatsAppIntegration,
                    WhatsAppIntegration.business_id == WhatsAppPhoneNumber.business_id,
                )
                .where(
                    WhatsAppPhoneNumber.environment == "live",
                    WhatsAppPhoneNumber.disconnected_at.is_(None),
                    WhatsAppPhoneNumber.deleted_at.is_(None),
                    WhatsAppIntegration.deleted_at.is_(None),
                    WhatsAppIntegration.status.in_(["connected", "provisioning"]),
                )
                .order_by(WhatsAppPhoneNumber.created_at.asc())
                .limit(self.max_batch_size)
            )
            pairs = rows.all()
            now = datetime.now(timezone.utc)
            for phone, integration in pairs:
                verification_status = str(phone.verification_status or "").strip().lower()
                health_status = str(phone.last_health_status or "").strip().lower()
                needs_registration = verification_status not in {"verified"} or health_status in {"pending", "error", "degraded"}
                if not needs_registration:
                    continue
                existing = await db.execute(
                    select(OutboxEvent.id)
                    .where(
                        OutboxEvent.event_type == "whatsapp.phone.register",
                        OutboxEvent.status == "pending",
                        OutboxEvent.business_id == phone.business_id,
                        OutboxEvent.payload_json["phone_number_id"].astext == phone.phone_number_id,
                        OutboxEvent.deleted_at.is_(None),
                    )
                    .limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    continue
                db.add(
                    OutboxEvent(
                        business_id=phone.business_id,
                        operation_id=f"reconcile_phone_{phone.phone_number_id}",
                        event_type="whatsapp.phone.register",
                        payload_json={
                            "business_id": str(phone.business_id),
                            "phone_number_id": str(phone.phone_number_id),
                            "onboarding_operation_id": "",
                            "onboarding_session_id": "",
                            "trigger": "reconcile_worker",
                        },
                        status="pending",
                        available_at=now,
                    )
                )
                await AuditLogService(db).write(
                    action="whatsapp.phone.register.reconcile_enqueue",
                    resource_type="whatsapp_phone_number",
                    status="success",
                    business_id=phone.business_id,
                    actor_type="system",
                    resource_id=phone.phone_number_id,
                    details={
                        "verification_status": phone.verification_status,
                        "health_status": phone.last_health_status,
                        "integration_status": integration.status,
                    },
                )
            await db.commit()


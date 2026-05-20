from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.domain.status_enums import CampaignStatus, CampaignRecipientStatus
from app.config import settings
from app.models.business_domains import (
    Campaign,
    CampaignRecipient,
    CampaignRecipientEvent,
    CampaignSendJob,
    MessageOutbox,
    OutboxEvent,
)
from app.services.campaign_finalize_enqueue_service import enqueue_campaign_finalize
from app.services.campaign_pause_service import CampaignPauseService
from app.services.campaign_blackbox_recorder import CampaignBlackBoxRecorder

logger = logging.getLogger(__name__)


class CampaignBatchDispatchWorker:
    def __init__(self, *, poll_interval_seconds: float = 1.0, default_batch_size: int = 1000) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.default_batch_size = max(500, min(5000, int(default_batch_size)))
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
                logger.exception("campaign_batch_dispatch_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "campaign_batch_dispatch_job",
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

            evt.attempts = int(evt.attempts or 0) + 1
            payload = evt.payload_json or {}
            try:
                campaign_id = UUID(str(payload["campaign_id"]))
            except Exception:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True

            batch_size = int(payload.get("batch_size") or self.default_batch_size)
            batch_size = max(500, min(5000, batch_size))
            campaign_execution_mode = str(payload.get("campaign_execution_mode") or "").strip().upper()
            rollout_phase = int(payload.get("rollout_phase") or 0)
            dispatched_count_so_far = int(payload.get("dispatched_count_so_far") or 0)
            cursor_after_raw = payload.get("cursor_after_recipient_id")
            cursor_after: UUID | None = None
            if cursor_after_raw:
                try:
                    cursor_after = UUID(str(cursor_after_raw))
                except Exception:
                    cursor_after = None

            campaign_row = await db.execute(
                select(Campaign)
                .where(Campaign.id == campaign_id, Campaign.deleted_at.is_(None))
                .with_for_update()
            )
            campaign = campaign_row.scalar_one_or_none()
            if campaign is None:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True
            if campaign.cancelled_at is not None or campaign.status == CampaignStatus.CANCELLED.value:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True
            if campaign.status == CampaignStatus.PAUSED.value or campaign.paused_at is not None:
                evt.status = "pending"
                evt.available_at = now + timedelta(seconds=30)
                await db.commit()
                return True
            if campaign.status != CampaignStatus.RUNNING.value:
                evt.status = "failed"
                evt.processed_at = now
                await db.commit()
                return True
            if not campaign_execution_mode:
                campaign_execution_mode = str((campaign.variable_mapping_json or {}).get("__execution_mode__") or "STANDARD").strip().upper()
            if campaign_execution_mode not in {"STANDARD", "SLOW_START", "AGGRESSIVE", "SAFE_MODE"}:
                campaign_execution_mode = "STANDARD"
            is_marketing = (campaign.template_category or "").lower() == "marketing"

            if is_marketing and campaign_execution_mode in {"SLOW_START", "SAFE_MODE"} and rollout_phase in {1, 2}:
                gate = await self._evaluate_rollout_gate(db=db, campaign_id=campaign.id)
                if not gate["allow"]:
                    await CampaignPauseService(db).pause_campaign(
                        business_id=campaign.business_id,
                        campaign_id=campaign.id,
                        reason="rollout_gate_failed",
                    )
                    await CampaignBlackBoxRecorder(db).record(
                        business_id=campaign.business_id,
                        campaign_id=campaign.id,
                        event_type="campaign_auto_paused",
                        message="Auto-paused by progressive rollout gate",
                        payload_json={
                            "reason_code": "rollout_gate_failed",
                            **gate,
                            "campaign_execution_mode": campaign_execution_mode,
                            "rollout_phase": rollout_phase,
                        },
                    )
                    evt.status = "processed"
                    evt.processed_at = now
                    await db.commit()
                    return True

            recipient_stmt = (
                select(CampaignRecipient)
                .where(
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.business_id == campaign.business_id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.eligibility_status == CampaignRecipientStatus.ELIGIBLE.value,
                    CampaignRecipient.status == CampaignRecipientStatus.PENDING.value,
                )
                .order_by(CampaignRecipient.id.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            if cursor_after is not None:
                recipient_stmt = recipient_stmt.where(CampaignRecipient.id > cursor_after)

            effective_limit = batch_size
            if is_marketing and campaign_execution_mode in {"SLOW_START", "SAFE_MODE"}:
                phase_limit = 100 if rollout_phase == 0 else (1000 if rollout_phase == 1 else None)
                if phase_limit is not None:
                    remaining_in_phase = max(0, phase_limit - dispatched_count_so_far)
                    if remaining_in_phase == 0:
                        db.add(
                            OutboxEvent(
                                business_id=campaign.business_id,
                                operation_id=f"campaign:{campaign.id}:batch:ramp:{rollout_phase + 1}",
                                event_type="campaign_batch_dispatch_job",
                                payload_json={
                                    "campaign_id": str(campaign.id),
                                    "business_id": str(campaign.business_id),
                                    "batch_size": batch_size,
                                    "cursor_after_recipient_id": str(cursor_after) if cursor_after else None,
                                    "campaign_execution_mode": campaign_execution_mode,
                                    "rollout_phase": rollout_phase + 1,
                                    "dispatched_count_so_far": 0,
                                },
                                status="pending",
                                available_at=now + timedelta(minutes=5),
                            )
                        )
                        evt.status = "processed"
                        evt.processed_at = now
                        await db.commit()
                        return True
                    effective_limit = min(batch_size, remaining_in_phase)
                    recipient_stmt = recipient_stmt.limit(effective_limit)
                else:
                    effective_limit = batch_size
                    recipient_stmt = recipient_stmt.limit(batch_size)

            recipients = list((await db.execute(recipient_stmt)).scalars().all())
            if not recipients:
                await enqueue_campaign_finalize(
                    db,
                    business_id=campaign.business_id,
                    campaign_id=campaign.id,
                    source="batch_dispatch_complete",
                    debounce_seconds=1,
                )
                evt.status = "processed"
                evt.processed_at = now
                await db.commit()
                return True

            last_id: UUID | None = None
            for recipient in recipients:
                payload_json = {
                    "to_phone_e164": recipient.phone_e164,
                    "template_id": str(campaign.template_id) if campaign.template_id else None,
                    "variables": recipient.variables_json or {},
                    "campaign_id": str(campaign.id),
                    "campaign_recipient_id": str(recipient.id),
                    "source": "campaign",
                }
                payload_hash = hashlib.sha256(
                    json.dumps(payload_json, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                idempotency_key = (
                    f"campaign:{campaign.id}:recipient:{recipient.id}:template:{campaign.template_id or 'none'}:version:{payload_hash}"
                )
                existing_row = await db.execute(
                    select(MessageOutbox).where(
                        MessageOutbox.idempotency_key == idempotency_key,
                        MessageOutbox.deleted_at.is_(None),
                    ).limit(1)
                )
                existing_outbox = existing_row.scalar_one_or_none()
                if existing_outbox is not None:
                    # Existing row already exists: never enqueue/send again.
                    # Do not mutate recipient to SENT here; webhook status worker is the sole owner
                    # of recipient status progression.
                    if recipient.status == CampaignRecipientStatus.PENDING.value:
                        recipient.status = CampaignRecipientStatus.QUEUED.value
                    last_id = recipient.id
                    continue

                outbox = MessageOutbox(
                    business_id=campaign.business_id,
                    campaign_id=campaign.id,
                    campaign_recipient_id=recipient.id,
                    conversation_id=None,
                    phone_number_id=campaign.phone_number_id or "",
                    to_phone_e164=recipient.phone_e164,
                    message_type="template" if campaign.template_id else "text",
                    template_id=campaign.template_id,
                    payload_json=payload_json,
                    source_type="campaign",
                    priority=100,
                    scheduled_at=now,
                    idempotency_key=idempotency_key,
                    status="pending",
                    attempt_count=0,
                )
                db.add(outbox)
                db.add(
                    CampaignSendJob(
                        campaign_id=campaign.id,
                        campaign_recipient_id=recipient.id,
                        business_id=campaign.business_id,
                        phone_number_id=campaign.phone_number_id or "",
                        status="pending",
                        attempt_count=0,
                        scheduled_at=now,
                    )
                )
                recipient.status = CampaignRecipientStatus.QUEUED.value
                db.add(
                    CampaignRecipientEvent(
                        campaign_id=campaign.id,
                        campaign_recipient_id=recipient.id,
                        business_id=campaign.business_id,
                        event_type="campaign_recipient.dispatch_queued",
                        old_status=CampaignRecipientStatus.PENDING.value,
                        new_status=CampaignRecipientStatus.QUEUED.value,
                        payload_json={
                            "message_outbox_idempotency_key": idempotency_key,
                        },
                    )
                )
                last_id = recipient.id

            next_dispatched_count = dispatched_count_so_far + len(recipients)
            if is_marketing and campaign_execution_mode in {"SLOW_START", "SAFE_MODE"}:
                phase_limit = 100 if rollout_phase == 0 else (1000 if rollout_phase == 1 else None)
                if phase_limit is not None and next_dispatched_count >= phase_limit and last_id is not None:
                    db.add(
                        OutboxEvent(
                            business_id=campaign.business_id,
                            operation_id=f"campaign:{campaign.id}:batch:ramp:{rollout_phase + 1}:{last_id}",
                            event_type="campaign_batch_dispatch_job",
                            payload_json={
                                "campaign_id": str(campaign.id),
                                "business_id": str(campaign.business_id),
                                "batch_size": batch_size,
                                "cursor_after_recipient_id": str(last_id),
                                "campaign_execution_mode": campaign_execution_mode,
                                "rollout_phase": rollout_phase + 1,
                                "dispatched_count_so_far": 0,
                            },
                            status="pending",
                            available_at=now + timedelta(minutes=5),
                        )
                    )
                    await CampaignBlackBoxRecorder(db).record(
                        business_id=campaign.business_id,
                        campaign_id=campaign.id,
                        event_type="rollout_stage_wait",
                        message=f"Completed rollout stage {rollout_phase}; waiting 5 minutes before next stage",
                        payload_json={
                            "campaign_execution_mode": campaign_execution_mode,
                            "completed_stage": rollout_phase,
                            "next_stage": rollout_phase + 1,
                            "wait_seconds": 300,
                            "stage_dispatched_count": next_dispatched_count,
                        },
                    )
                elif len(recipients) == effective_limit and last_id is not None:
                    db.add(
                        OutboxEvent(
                            business_id=campaign.business_id,
                            operation_id=f"campaign:{campaign.id}:batch:{last_id}",
                            event_type="campaign_batch_dispatch_job",
                            payload_json={
                                "campaign_id": str(campaign.id),
                                "business_id": str(campaign.business_id),
                                "batch_size": batch_size,
                                "cursor_after_recipient_id": str(last_id),
                                "campaign_execution_mode": campaign_execution_mode,
                                "rollout_phase": rollout_phase,
                                "dispatched_count_so_far": next_dispatched_count,
                            },
                            status="pending",
                            available_at=now,
                        )
                    )
            elif len(recipients) == batch_size and last_id is not None:
                db.add(
                    OutboxEvent(
                        business_id=campaign.business_id,
                        operation_id=f"campaign:{campaign.id}:batch:{last_id}",
                        event_type="campaign_batch_dispatch_job",
                        payload_json={
                            "campaign_id": str(campaign.id),
                            "business_id": str(campaign.business_id),
                            "batch_size": batch_size,
                            "cursor_after_recipient_id": str(last_id),
                        },
                        status="pending",
                        available_at=now,
                    )
                )

            evt.status = "processed"
            evt.processed_at = now
            await db.commit()
            return True

    async def _evaluate_rollout_gate(self, *, db, campaign_id: UUID) -> dict:
        total_row = await self._count_recipients(db=db, campaign_id=campaign_id)
        failed_row = await self._count_failed(db=db, campaign_id=campaign_id)
        blocked_row = await self._count_blocked(db=db, campaign_id=campaign_id)
        unsub_row = await self._count_unsubscribed(db=db, campaign_id=campaign_id)

        total = int(total_row or 0)
        failed = int(failed_row or 0)
        blocked = int(blocked_row or 0)
        unsub = int(unsub_row or 0)
        failed_rate = (float(failed) / float(total)) if total else 0.0
        blocked_rate = (float(blocked) / float(total)) if total else 0.0
        unsubscribe_rate = (float(unsub) / float(total)) if total else 0.0

        allow = True
        if total >= 20:
            allow = (
                failed_rate <= float(settings.QUALITY_GUARD_FAILED_RATE_15M_THRESHOLD)
                and unsubscribe_rate <= float(settings.QUALITY_GUARD_UNSUBSCRIBE_RATE_THRESHOLD)
                and blocked_rate <= 0.03
            )
        return {
            "allow": allow,
            "observed_total": total,
            "failed_rate": round(failed_rate, 4),
            "blocked_rate": round(blocked_rate, 4),
            "unsubscribe_rate": round(unsubscribe_rate, 4),
        }

    async def _count_recipients(self, *, db, campaign_id: UUID) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(CampaignRecipient.id)).where(
                        CampaignRecipient.campaign_id == campaign_id,
                        CampaignRecipient.deleted_at.is_(None),
                        CampaignRecipient.status.in_(["sent", "delivered", "read", "replied", "failed"]),
                    )
                )
            ).scalar_one()
            or 0
        )

    async def _count_failed(self, *, db, campaign_id: UUID) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(CampaignRecipient.id)).where(
                        CampaignRecipient.campaign_id == campaign_id,
                        CampaignRecipient.deleted_at.is_(None),
                        CampaignRecipient.status == "failed",
                    )
                )
            ).scalar_one()
            or 0
        )

    async def _count_blocked(self, *, db, campaign_id: UUID) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(CampaignRecipient.id)).where(
                        CampaignRecipient.campaign_id == campaign_id,
                        CampaignRecipient.deleted_at.is_(None),
                        (
                            CampaignRecipient.eligibility_reason.ilike("%blocked%")
                            | CampaignRecipient.last_error_code.in_(["131047", "131048"])
                        ),
                    )
                )
            ).scalar_one()
            or 0
        )

    async def _count_unsubscribed(self, *, db, campaign_id: UUID) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(CampaignRecipient.id)).where(
                        CampaignRecipient.campaign_id == campaign_id,
                        CampaignRecipient.deleted_at.is_(None),
                        (
                            CampaignRecipient.eligibility_reason.ilike("%opted_out%")
                            | CampaignRecipient.eligibility_reason.ilike("%unsubscribed%")
                        ),
                    )
                )
            ).scalar_one()
            or 0
        )

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select

from app.database import AsyncSessionLocal
from app.domain.status_enums import CampaignRecipientStatus, CampaignStatus
from app.models.business import Business
from app.models.business_domains import (
    Campaign,
    CampaignRecipient,
    CampaignSendJob,
    MessageOutbox,
    OutboxEvent,
)
from app.services.campaign_finalize_enqueue_service import enqueue_campaign_finalize
from app.services.contact_frequency_service import ContactFrequencyService
from app.services.campaign_quality_guard_service import CampaignQualityGuardService
from app.services.rate_limiter_service import rate_limiter_service
from app.services.whatsapp_messaging_service import WhatsAppMessagingService
from app.services.whatsapp_client import WhatsAppClientError
from app.services.campaign_blackbox_recorder import CampaignBlackBoxRecorder
from app.services.campaign_pause_service import CampaignPauseService
from app.services.queue_routing_service import worker_region_normalized
from app.services.tenant_rate_orchestrator_service import TenantRateOrchestratorService
from app.services.observability_metrics import metrics

logger = logging.getLogger(__name__)


class MessageSendWorker:
    def __init__(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        max_attempts: int = 8,
        max_batch_size: int = 20,
        max_parallelism: int = 5,
    ) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.max_attempts = max_attempts
        self.max_batch_size = max(1, int(max_batch_size))
        self.max_parallelism = max(1, int(max_parallelism))
        self._last_parallelism = self.max_parallelism
        self._campaign_rate_limit_hits: dict[str, int] = {}
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
                logger.exception("message_send_worker_loop_failed")
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
                    logger.exception("message_send_worker_batch_item_failed", exc_info=result)
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
        region = worker_region_normalized()
        async with AsyncSessionLocal() as db:
            region_clause = True if region == "global" else func.upper(Business.data_region) == region.upper()
            pending_q = await db.execute(
                select(MessageOutbox.id)
                .join(Business, Business.id == MessageOutbox.business_id)
                .where(
                    MessageOutbox.status == "pending",
                    (MessageOutbox.next_retry_at.is_(None) | (MessageOutbox.next_retry_at <= now)),
                    MessageOutbox.deleted_at.is_(None),
                    region_clause,
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
        region = worker_region_normalized()
        async with AsyncSessionLocal() as db:
            region_clause = True if region == "global" else func.upper(Business.data_region) == region.upper()
            outbox_row = await db.execute(
                select(MessageOutbox)
                .join(Business, Business.id == MessageOutbox.business_id)
                .where(
                    MessageOutbox.status == "pending",
                    MessageOutbox.scheduled_at <= now,
                    (MessageOutbox.next_retry_at.is_(None) | (MessageOutbox.next_retry_at <= now)),
                    MessageOutbox.deleted_at.is_(None),
                    region_clause,
                )
                .order_by(
                    case(
                        (MessageOutbox.source_type.in_(["otp", "inbox_reply", "support_reply"]), 0),
                        (MessageOutbox.source_type.in_(["utility", "order_update", "transactional"]), 1),
                        (MessageOutbox.source_type.in_(["automation", "workflow"]), 2),
                        (MessageOutbox.source_type.in_(["campaign_test", "campaign", "campaign_retry"]), 3),
                        else_=4,
                    ).asc(),
                    MessageOutbox.priority.asc(),
                    MessageOutbox.scheduled_at.asc(),
                    MessageOutbox.created_at.asc(),
                    MessageOutbox.id.asc(),
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            outbox = outbox_row.scalar_one_or_none()
            if outbox is None:
                return False

            # Step 2: idempotency key check (defensive)
            dup = await db.execute(
                select(MessageOutbox)
                .where(
                    MessageOutbox.idempotency_key == outbox.idempotency_key,
                    MessageOutbox.id != outbox.id,
                    MessageOutbox.provider_message_id.is_not(None),
                    MessageOutbox.deleted_at.is_(None),
                )
                .order_by(MessageOutbox.created_at.desc())
                .limit(1)
            )
            existing = dup.scalar_one_or_none()
            if existing is not None:
                outbox.status = "sent"
                outbox.provider_message_id = existing.provider_message_id
                await db.commit()
                return True

            campaign: Campaign | None = None
            recipient: CampaignRecipient | None = None

            if outbox.campaign_id is not None:
                c_row = await db.execute(
                    select(Campaign)
                    .where(Campaign.id == outbox.campaign_id, Campaign.deleted_at.is_(None))
                    .with_for_update()
                )
                campaign = c_row.scalar_one_or_none()
                if campaign is None:
                    outbox.status = "cancelled"
                    outbox.error_code = "campaign_not_dispatchable"
                    outbox.error_message = "Campaign missing"
                    await db.commit()
                    return True
                if campaign.status == CampaignStatus.PAUSED.value:
                    outbox.status = "pending"
                    outbox.next_retry_at = now + timedelta(seconds=30)
                    await db.commit()
                    return True
                if campaign.status == CampaignStatus.CANCELLED.value:
                    outbox.status = "cancelled"
                    outbox.error_code = "campaign_cancelled"
                    outbox.error_message = "Campaign cancelled"
                    await db.commit()
                    return True
                quality = await CampaignQualityGuardService(db).evaluate_and_apply(campaign=campaign)
                if quality.action in {"pause", "stop_marketing"}:
                    await CampaignBlackBoxRecorder(db).record(
                        business_id=outbox.business_id,
                        campaign_id=campaign.id,
                        event_type="quality_guard_action",
                        message=f"Campaign action triggered by quality guard: {quality.action}",
                        payload_json={"action": quality.action},
                    )
                    outbox.status = "pending"
                    outbox.next_retry_at = now + timedelta(seconds=60)
                    await db.commit()
                    return True
                if quality.action == "throttle":
                    await CampaignBlackBoxRecorder(db).record(
                        business_id=outbox.business_id,
                        campaign_id=campaign.id,
                        event_type="throughput_reduced",
                        message=f"Campaign throughput reduced by quality guard to delay {int(quality.throttle_seconds or 30)}s",
                        payload_json={"throttle_seconds": int(quality.throttle_seconds or 30)},
                    )
                    outbox.status = "pending"
                    outbox.next_retry_at = now + timedelta(seconds=max(10, int(quality.throttle_seconds or 30)))
                    await db.commit()
                    return True

            if outbox.campaign_recipient_id is not None:
                r_row = await db.execute(
                    select(CampaignRecipient)
                    .where(
                        CampaignRecipient.id == outbox.campaign_recipient_id,
                        CampaignRecipient.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                recipient = r_row.scalar_one_or_none()
                if recipient is None or recipient.status not in {
                    CampaignRecipientStatus.QUEUED.value,
                    CampaignRecipientStatus.RESERVED.value,
                }:
                    outbox.status = "cancelled"
                    outbox.error_code = "recipient_not_sendable"
                    outbox.error_message = "Recipient is not queued/reserved"
                    await db.commit()
                    return True

            orchestration = await TenantRateOrchestratorService(db).evaluate(
                business_id=outbox.business_id,
                phone_number_id=outbox.phone_number_id,
                source_type=outbox.source_type,
            )
            source_type = str(outbox.source_type or "unknown")
            business_tag = str(outbox.business_id)
            if not orchestration.allowed:
                metrics.increment(
                    "whatsapp_send_orchestration_decision_total",
                    tags={
                        "decision": "blocked",
                        "reason": str(orchestration.reason or "unknown"),
                        "source_type": source_type,
                        "business_id": business_tag,
                    },
                )
                if outbox.campaign_id is not None and campaign is not None:
                    await CampaignBlackBoxRecorder(db).record(
                        business_id=outbox.business_id,
                        campaign_id=campaign.id,
                        event_type="send_orchestration_backoff",
                        message=f"Orchestrator deferred send by {int(orchestration.retry_after_seconds)}s",
                        payload_json={
                            "reason": orchestration.reason,
                            "retry_after_seconds": int(orchestration.retry_after_seconds),
                            "phone_number_id": outbox.phone_number_id,
                            "source_type": outbox.source_type,
                        },
                    )
                outbox.next_retry_at = now + timedelta(seconds=max(1, int(orchestration.retry_after_seconds)))
                await db.commit()
                return True
            metrics.increment(
                "whatsapp_send_orchestration_decision_total",
                tags={
                    "decision": "allowed",
                    "reason": str(orchestration.reason or "none"),
                    "source_type": source_type,
                    "business_id": business_tag,
                },
            )

            throttle = await rate_limiter_service.check_send_limits(
                business_id=str(outbox.business_id),
                phone_number_id=outbox.phone_number_id,
                waba_id=(campaign.waba_id if campaign else None),
                campaign_id=(str(outbox.campaign_id) if outbox.campaign_id else None),
                contact_id=(str(recipient.contact_id) if recipient and recipient.contact_id else None),
                is_retry=int(outbox.attempt_count or 0) > 0,
                template_category=(campaign.template_category if campaign else None),
                throughput_multiplier=orchestration.throughput_multiplier,
            )
            if not throttle.allowed:
                metrics.increment(
                    "whatsapp_send_rate_limit_decision_total",
                    tags={
                        "decision": "blocked",
                        "blocked_by": str(throttle.blocked_by or "unknown"),
                        "source_type": source_type,
                        "business_id": business_tag,
                    },
                )
                if outbox.campaign_id is not None and campaign is not None:
                    campaign_key = str(outbox.campaign_id)
                    self._campaign_rate_limit_hits[campaign_key] = int(self._campaign_rate_limit_hits.get(campaign_key, 0)) + 1
                    if self._campaign_rate_limit_hits[campaign_key] >= 5:
                        await CampaignPauseService(db).pause_campaign(
                            business_id=outbox.business_id,
                            campaign_id=outbox.campaign_id,
                            reason="auto_pause_repeated_rate_limit",
                        )
                        await CampaignBlackBoxRecorder(db).record(
                            business_id=outbox.business_id,
                            campaign_id=outbox.campaign_id,
                            event_type="campaign_auto_paused",
                            message="Auto-paused because repeated rate-limit blocks were detected",
                            payload_json={
                                "reason_code": "repeated_rate_limit_errors",
                                "blocked_by": throttle.blocked_by,
                                "retry_after_seconds": int(throttle.retry_after_seconds),
                                "consecutive_blocks": self._campaign_rate_limit_hits[campaign_key],
                            },
                        )
                        self._campaign_rate_limit_hits[campaign_key] = 0
                        outbox.next_retry_at = now + timedelta(seconds=max(30, int(throttle.retry_after_seconds)))
                        await db.commit()
                        return True
                if outbox.campaign_id is not None and campaign is not None:
                    await CampaignBlackBoxRecorder(db).record(
                        business_id=outbox.business_id,
                        campaign_id=campaign.id,
                        event_type="rate_limiter_backoff",
                        message=f"Rate limiter deferred send by {int(throttle.retry_after_seconds)}s",
                        payload_json={
                            "retry_after_seconds": int(throttle.retry_after_seconds),
                            "phone_number_id": outbox.phone_number_id,
                            "blocked_by": throttle.blocked_by,
                            "source_type": outbox.source_type,
                        },
                    )
                outbox.next_retry_at = now + timedelta(seconds=max(1, int(throttle.retry_after_seconds)))
                await db.commit()
                return True
            metrics.increment(
                "whatsapp_send_rate_limit_decision_total",
                tags={
                    "decision": "allowed",
                    "blocked_by": "none",
                    "source_type": source_type,
                    "business_id": business_tag,
                },
            )
            if outbox.campaign_id is not None:
                self._campaign_rate_limit_hits[str(outbox.campaign_id)] = 0

            outbox.status = "sending"
            outbox.attempt_count = int(outbox.attempt_count or 0) + 1
            await db.flush()

            sender = WhatsAppMessagingService(db)
            frequency = ContactFrequencyService(db)
            try:
                is_dry_run = campaign is not None and (campaign.environment or "").lower() == "dry_run"
                if outbox.message_type == "template":
                    if campaign is None:
                        raise ValueError("Campaign context required for template send")
                    if (campaign.template_category or "").lower() == "marketing":
                        await frequency.assert_can_send_marketing(
                            business_id=outbox.business_id,
                            contact_id=(recipient.contact_id if recipient else None),
                            phone_e164=outbox.to_phone_e164,
                        )
                    if is_dry_run:
                        result = None
                    else:
                        result = await sender.send_template(
                            business_id=outbox.business_id,
                            to=outbox.to_phone_e164,
                            phone_number_id=outbox.phone_number_id,
                            waba_id=campaign.waba_id or "",
                            template_name=campaign.template_name or "",
                            language=campaign.template_language or "",
                            template_category=campaign.template_category or "utility",
                            components=(outbox.payload_json or {}).get("components"),
                        )
                else:
                    text_body = str((outbox.payload_json or {}).get("text") or "")
                    if not text_body:
                        raise ValueError("Missing text payload for text message")
                    if is_dry_run:
                        result = None
                    else:
                        result = await sender.send_text(
                            business_id=outbox.business_id,
                            to=outbox.to_phone_e164,
                            text=text_body,
                            phone_number_id=outbox.phone_number_id,
                            contact_id=str(recipient.contact_id) if recipient and recipient.contact_id else outbox.to_phone_e164,
                        )

                provider_message_id = None
                if is_dry_run:
                    provider_message_id = f"dryrun:{outbox.id}"
                else:
                    try:
                        provider_message_id = ((result.provider_payload or {}).get("messages") or [{}])[0].get("id")
                    except Exception:
                        provider_message_id = None

                outbox.status = "sent"
                outbox.provider_message_id = provider_message_id
                outbox.error_code = None
                outbox.error_message = None
                if campaign is not None and (campaign.template_category or "").lower() == "marketing":
                    await frequency.record_marketing_send(
                        business_id=outbox.business_id,
                        contact_id=(recipient.contact_id if recipient else None),
                        phone_e164=outbox.to_phone_e164,
                    )

                if recipient is not None:
                    if is_dry_run:
                        recipient.status = CampaignRecipientStatus.SENT.value
                    job_row = await db.execute(
                        select(CampaignSendJob)
                        .where(
                            CampaignSendJob.campaign_id == recipient.campaign_id,
                            CampaignSendJob.campaign_recipient_id == recipient.id,
                            CampaignSendJob.deleted_at.is_(None),
                        )
                        .order_by(CampaignSendJob.created_at.desc())
                        .limit(1)
                    )
                    job = job_row.scalar_one_or_none()
                    if job is not None:
                        job.status = "completed"
                        job.completed_at = datetime.now(timezone.utc)
                if is_dry_run and campaign is not None:
                    await CampaignBlackBoxRecorder(db).record(
                        business_id=outbox.business_id,
                        campaign_id=campaign.id,
                        event_type="dry_run_send_simulated",
                        message="Dry run simulated send with provider call skipped",
                        payload_json={
                            "outbox_id": str(outbox.id),
                            "campaign_recipient_id": str(outbox.campaign_recipient_id) if outbox.campaign_recipient_id else None,
                            "to_phone_e164": outbox.to_phone_e164,
                            "rate_limit_plan": {
                                "blocked_by": throttle.blocked_by,
                                "retry_after_seconds": int(throttle.retry_after_seconds or 0),
                            },
                            "billing_hold_simulated": True,
                        },
                    )
                if outbox.campaign_id is not None:
                    await enqueue_campaign_finalize(
                        db,
                        business_id=outbox.business_id,
                        campaign_id=outbox.campaign_id,
                        source="send_success",
                        debounce_seconds=5,
                    )

            except WhatsAppClientError as exc:
                extracted_provider_id = self._extract_provider_message_id_from_error(exc)
                if extracted_provider_id:
                    # Provider accepted request but client path failed after response parsing.
                    outbox.status = "sent"
                    outbox.provider_message_id = extracted_provider_id
                    outbox.error_code = None
                    outbox.error_message = None
                else:
                    retryable, uncertain_timeout = self._classify_retryable_provider_error(exc)
                    outbox.error_code = exc.provider_error_code or str(exc.status_code or "provider_error")
                    outbox.error_message = str(exc)
                    if uncertain_timeout:
                        # Unknown delivery state: do not blindly retry as new message.
                        outbox.status = "unknown"
                        outbox.next_retry_at = None
                    elif retryable and int(outbox.attempt_count or 0) < self.max_attempts:
                        retry_base = min(300, 2 ** int(outbox.attempt_count or 1))
                        if exc.status_code == 429:
                            retry_base = min(600, max(retry_base, 30))
                        outbox.status = "pending"
                        outbox.next_retry_at = datetime.now(timezone.utc) + timedelta(
                            seconds=retry_base
                        )
                    else:
                        outbox.status = "failed"
                        if outbox.campaign_id is not None:
                            await enqueue_campaign_finalize(
                                db,
                                business_id=outbox.business_id,
                                campaign_id=outbox.campaign_id,
                                source="retry_exhausted",
                                debounce_seconds=5,
                            )
                    if recipient is not None:
                        recipient.last_error_code = outbox.error_code
                        recipient.last_error_message = outbox.error_message
            except Exception as exc:
                outbox.error_code = "send_worker_error"
                outbox.error_message = str(exc)
                outbox.status = "failed"
                if recipient is not None:
                    recipient.last_error_code = outbox.error_code
                    recipient.last_error_message = outbox.error_message

            await db.commit()
            return True

    @staticmethod
    def _extract_provider_message_id_from_error(exc: WhatsAppClientError) -> str | None:
        body = exc.response_body or ""
        if not body:
            return None
        try:
            parsed = json.loads(body)
            maybe = ((parsed.get("messages") or [{}])[0] or {}).get("id")
            return str(maybe) if maybe else None
        except Exception:
            return None

    @staticmethod
    def _classify_retryable_provider_error(exc: WhatsAppClientError) -> tuple[bool, bool]:
        """
        Returns: (retryable, uncertain_timeout)
        uncertain_timeout=True means API timeout/transport ambiguity with unknown acceptance state.
        """
        status = int(exc.status_code or 0)
        code = str(exc.provider_error_code or "").strip()
        msg = str(exc).lower()

        # Timeout/transport uncertainty: do not blindly auto-retry as new message.
        if status == 0 and any(k in msg for k in ["timeout", "timed out", "connection reset", "connection aborted"]):
            return False, True

        # Retryable transients: 429 and 5xx.
        if status == 429 or status >= 500:
            return True, False

        # Explicit non-retryable provider/business/policy/content failures.
        non_retryable_codes = {
            "131026",  # invalid recipient / cannot receive
            "131047",  # policy block
            "131048",  # spam rate/quality enforcement
            "132000",  # template param mismatch / missing variable
            "132001",  # template does not exist or rejected
            "132015",  # template paused/rejected state variants
            "200",     # permissions / suspended style errors
            "10",      # permission denied
        }
        if code in non_retryable_codes:
            return False, False

        # Safe default: non-retryable unless clearly transient.
        return False, False

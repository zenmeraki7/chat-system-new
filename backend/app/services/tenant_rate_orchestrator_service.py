from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.business_domains import MessageOutbox, OutboxEvent, WhatsAppPhoneNumber


_HIGH_PRIORITY_SOURCES = {"otp", "inbox_reply", "support_reply"}
_CAMPAIGN_SOURCES = {"campaign", "campaign_test", "campaign_retry"}


@dataclass
class RateOrchestrationDecision:
    allowed: bool
    retry_after_seconds: int
    reason: str | None
    throughput_multiplier: float


class TenantRateOrchestratorService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate(
        self,
        *,
        business_id: UUID,
        phone_number_id: str,
        source_type: str | None,
    ) -> RateOrchestrationDecision:
        source = str(source_type or "").strip().lower()
        multiplier = 1.0

        phone = (
            await self.db.execute(
                select(WhatsAppPhoneNumber)
                .where(
                    WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                    WhatsAppPhoneNumber.deleted_at.is_(None),
                )
                .limit(1)
            )
        ).scalars().first()
        if phone is not None:
            status = str(phone.status or "").strip().lower()
            quality = str(phone.quality_rating or "").strip().lower()
            if status in {"disconnected", "inactive", "suspended"}:
                return RateOrchestrationDecision(
                    allowed=False,
                    retry_after_seconds=max(60, int(settings.RATE_LIMIT_RED_QUALITY_RETRY_AFTER_SECONDS)),
                    reason="phone_status_not_sendable",
                    throughput_multiplier=0.0,
                )
            if quality in {"red", "low"}:
                return RateOrchestrationDecision(
                    allowed=False,
                    retry_after_seconds=max(60, int(settings.RATE_LIMIT_RED_QUALITY_RETRY_AFTER_SECONDS)),
                    reason="phone_quality_red",
                    throughput_multiplier=0.0,
                )
            if quality in {"yellow", "medium"}:
                multiplier *= max(
                    float(settings.RATE_LIMIT_MIN_DYNAMIC_MULTIPLIER),
                    float(settings.RATE_LIMIT_YELLOW_QUALITY_MULTIPLIER),
                )
            elif quality in {"green", "high"}:
                multiplier *= max(0.2, float(settings.RATE_LIMIT_GREEN_QUALITY_MULTIPLIER))
            else:
                multiplier *= max(
                    float(settings.RATE_LIMIT_MIN_DYNAMIC_MULTIPLIER),
                    float(settings.RATE_LIMIT_UNKNOWN_QUALITY_MULTIPLIER),
                )

        failure_window_start = datetime.now(timezone.utc) - timedelta(
            minutes=max(1, int(settings.RATE_LIMIT_FAILURE_WINDOW_MINUTES))
        )
        totals = await self.db.execute(
            select(
                func.count(MessageOutbox.id),
                func.sum(case((MessageOutbox.status == "failed", 1), else_=0)),
            ).where(
                MessageOutbox.business_id == business_id,
                MessageOutbox.created_at >= failure_window_start,
                MessageOutbox.deleted_at.is_(None),
            )
        )
        total_count, failed_count = totals.one()
        total = int(total_count or 0)
        failed = int(failed_count or 0)
        if total >= 20:
            failure_rate = failed / float(total)
            if failure_rate >= float(settings.RATE_LIMIT_FAILURE_RATE_PAUSE_THRESHOLD):
                return RateOrchestrationDecision(
                    allowed=False,
                    retry_after_seconds=60,
                    reason="tenant_failure_rate_high",
                    throughput_multiplier=0.0,
                )
            if failure_rate >= float(settings.RATE_LIMIT_FAILURE_RATE_THROTTLE_THRESHOLD):
                multiplier *= 0.5

        if source not in _HIGH_PRIORITY_SOURCES:
            pending_webhook = (
                await self.db.execute(
                    select(func.count(OutboxEvent.id)).where(
                        OutboxEvent.status == "pending",
                        OutboxEvent.deleted_at.is_(None),
                        OutboxEvent.event_type.in_(["webhook.process.whatsapp", "webhook.status.whatsapp"]),
                    )
                )
            ).scalar_one()
            if int(pending_webhook or 0) >= int(settings.RATE_LIMIT_WEBHOOK_BACKPRESSURE_PENDING_THRESHOLD):
                if source in _CAMPAIGN_SOURCES:
                    return RateOrchestrationDecision(
                        allowed=False,
                        retry_after_seconds=max(5, int(settings.RATE_LIMIT_WEBHOOK_BACKPRESSURE_RETRY_AFTER_SECONDS)),
                        reason="webhook_backpressure",
                        throughput_multiplier=0.0,
                    )
                multiplier *= 0.75

        multiplier = max(float(settings.RATE_LIMIT_MIN_DYNAMIC_MULTIPLIER), min(1.0, float(multiplier)))
        return RateOrchestrationDecision(
            allowed=True,
            retry_after_seconds=0,
            reason=None,
            throughput_multiplier=multiplier,
        )


tenant_rate_orchestrator_service = TenantRateOrchestratorService

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.business import Business
from app.models.business_domains import Campaign, CampaignRecipient, MessageOutbox, OutboxEvent, WhatsAppMessageTemplate, WhatsAppPhoneNumber
from app.services.campaign_pause_service import CampaignPauseService
from app.services.campaign_blackbox_recorder import CampaignBlackBoxRecorder


@dataclass
class CampaignQualityDecision:
    action: str  # allow|throttle|pause|stop_marketing
    reason: str | None = None
    throttle_seconds: int = 0


class CampaignQualityGuardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate_and_apply(self, *, campaign: Campaign) -> CampaignQualityDecision:
        if campaign.deleted_at is not None:
            return CampaignQualityDecision(action="pause", reason="campaign_deleted")
        if (campaign.status or "").lower() in {"paused", "cancelled", "completed", "completed_with_failures", "failed"}:
            return CampaignQualityDecision(action="allow")
        business = (
            await self.db.execute(
                select(Business).where(
                    Business.id == campaign.business_id,
                    Business.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if business and (business.billing_status or "").lower() in {"payment_failed", "suspended"}:
            await self._pause(
                campaign,
                "quality_guard_wallet_risk",
                message="Auto-paused because wallet/billing may not cover remaining recipients",
                payload={"reason_code": "wallet_balance_risk", "billing_status": business.billing_status},
            )
            return CampaignQualityDecision(action="pause", reason="wallet_balance_risk")

        phone = (
            await self.db.execute(
                select(WhatsAppPhoneNumber).where(
                    WhatsAppPhoneNumber.business_id == campaign.business_id,
                    WhatsAppPhoneNumber.phone_number_id == campaign.phone_number_id,
                    WhatsAppPhoneNumber.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if phone is None:
            await self._pause(
                campaign,
                "quality_guard_missing_phone",
                message="Auto-paused because WhatsApp phone mapping is missing",
                payload={"reason_code": "phone_missing"},
            )
            return CampaignQualityDecision(action="pause", reason="phone_missing")

        phone_status = (phone.status or "").lower()
        quality = (phone.quality_rating or "").lower()
        tier = (phone.messaging_limit_tier or "").lower()
        if phone_status != "active" or phone.disabled_at is not None or phone.disconnected_at is not None:
            await self._pause(
                campaign,
                "quality_guard_phone_unhealthy",
                message="Auto-paused because phone number is disconnected/unhealthy",
                payload={"reason_code": "phone_unhealthy", "phone_status": phone_status, "quality_rating": quality},
            )
            return CampaignQualityDecision(action="pause", reason="phone_unhealthy")

        template = (
            await self.db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == campaign.template_id,
                    WhatsAppMessageTemplate.business_id == campaign.business_id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if template is None or (template.status or "").lower() not in {"approved", "active"}:
            await self._pause(
                campaign,
                "quality_guard_template_unhealthy",
                message="Auto-paused because template is not approved/active",
                payload={"reason_code": "template_unhealthy"},
            )
            return CampaignQualityDecision(action="pause", reason="template_unhealthy")

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=15)
        # Recent failed rate from recent final state timestamps.
        total_recent = (
            await self.db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    (
                        (CampaignRecipient.sent_at >= window_start)
                        | (CampaignRecipient.delivered_at >= window_start)
                        | (CampaignRecipient.read_at >= window_start)
                        | (CampaignRecipient.failed_at >= window_start)
                    ),
                )
            )
        ).scalar_one()
        failed_recent = (
            await self.db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.failed_at.is_not(None),
                    CampaignRecipient.failed_at >= window_start,
                )
            )
        ).scalar_one()
        failed_rate = (float(failed_recent or 0) / float(total_recent or 1)) if total_recent else 0.0
        if failed_rate > float(settings.QUALITY_GUARD_FAILED_RATE_15M_THRESHOLD):
            await self._pause(
                campaign,
                "quality_guard_failed_rate",
                message=f"Auto-paused because delivery failure rate reached {failed_rate * 100:.1f}% in 15 minutes",
                payload={
                    "reason_code": "failed_rate_high",
                    "window_minutes": 15,
                    "failed_rate": failed_rate,
                    "failed_count": int(failed_recent or 0),
                    "total_count": int(total_recent or 0),
                },
            )
            await self._notify(campaign, "campaign.auto_paused.failed_rate", {"failed_rate_last_15m": failed_rate})
            return CampaignQualityDecision(action="pause", reason="failed_rate_high")

        # Approximate unsubscribe/block rate from explicit opt-out-like skip reasons and policy failures.
        unsub_recent = (
            await self.db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.updated_at >= window_start,
                    (
                        CampaignRecipient.eligibility_reason.ilike("%opted_out%")
                        | CampaignRecipient.eligibility_reason.ilike("%unsubscribed%")
                        | CampaignRecipient.last_error_code.in_(["131047", "131048"])
                    ),
                )
            )
        ).scalar_one()
        unsubscribe_rate = (float(unsub_recent or 0) / float(total_recent or 1)) if total_recent else 0.0
        if unsubscribe_rate > float(settings.QUALITY_GUARD_UNSUBSCRIBE_RATE_THRESHOLD):
            delay = max(10, int(settings.QUALITY_GUARD_THROTTLE_DELAY_SECONDS))
            await self._throttle(campaign, delay)
            await CampaignBlackBoxRecorder(self.db).record(
                business_id=campaign.business_id,
                campaign_id=campaign.id,
                event_type="campaign_slowed",
                message=f"Campaign slowed because unsubscribe rate is high ({unsubscribe_rate * 100:.2f}% in 15m)",
                payload_json={
                    "reason_code": "unsubscribe_rate_high",
                    "unsubscribe_rate": unsubscribe_rate,
                    "window_minutes": 15,
                    "throttle_seconds": delay,
                },
            )
            await self._notify(
                campaign,
                "campaign.throttled.unsubscribe_rate",
                {"unsubscribe_rate_last_15m": unsubscribe_rate, "delay_seconds": delay},
            )
            return CampaignQualityDecision(action="throttle", reason="unsubscribe_rate_high", throttle_seconds=delay)

        # Phone quality RED: stop marketing sends.
        if quality in {"red", "low"} and (campaign.template_category or "").lower() == "marketing":
            await self._pause(
                campaign,
                "quality_guard_phone_red_marketing_stopped",
                message="Auto-paused because phone quality is red/low for marketing campaign",
                payload={"reason_code": "phone_quality_red", "quality_rating": quality},
            )
            await self._notify(campaign, "campaign.auto_paused.phone_quality_red", {"quality_rating": quality})
            return CampaignQualityDecision(action="stop_marketing", reason="phone_quality_red")

        # Conservative throttling on low messaging tiers.
        if tier in {"tier_1k", "tier_250", "limited", "low"} and (campaign.status or "").lower() in {"running", "queued"}:
            delay = max(10, int(settings.QUALITY_GUARD_THROTTLE_DELAY_SECONDS))
            await self._throttle(campaign, delay)
            return CampaignQualityDecision(action="throttle", reason="low_messaging_tier", throttle_seconds=delay)

        return CampaignQualityDecision(action="allow")

    async def _pause(self, campaign: Campaign, reason: str, *, message: str, payload: dict) -> None:
        if (campaign.status or "").lower() == "paused":
            return
        await CampaignPauseService(self.db).pause_campaign(
            business_id=campaign.business_id,
            campaign_id=campaign.id,
            reason=reason,
        )
        await CampaignBlackBoxRecorder(self.db).record(
            business_id=campaign.business_id,
            campaign_id=campaign.id,
            event_type="campaign_auto_paused",
            message=message,
            payload_json=payload,
        )

    async def _throttle(self, campaign: Campaign, delay_seconds: int) -> None:
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        rows = (
            await self.db.execute(
                select(MessageOutbox).where(
                    MessageOutbox.campaign_id == campaign.id,
                    MessageOutbox.business_id == campaign.business_id,
                    MessageOutbox.status == "pending",
                    MessageOutbox.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for row in rows:
            row.next_retry_at = retry_at

    async def _notify(self, campaign: Campaign, event_type: str, payload: dict) -> None:
        self.db.add(
            OutboxEvent(
                business_id=campaign.business_id,
                operation_id=f"campaign:{campaign.id}",
                event_type=event_type,
                payload_json={"campaign_id": str(campaign.id), **payload},
                status="pending",
            )
        )

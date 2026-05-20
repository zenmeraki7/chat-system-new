from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.domain.status_enums import CampaignStatus
from app.models.business import Business
from app.models.business_domains import (
    Campaign,
    CampaignRecipient,
    CampaignSendJob,
    CampaignStatusEvent,
    MessageOutbox,
    WhatsAppMessageTemplate,
    WhatsAppPhoneNumber,
)


class CampaignResumeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def resume_campaign(self, *, business_id: UUID, campaign_id: UUID, reason: str | None = None) -> Campaign:
        campaign = (
            await self.db.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id,
                    Campaign.business_id == business_id,
                    Campaign.deleted_at.is_(None),
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if not campaign:
            raise NotFoundException("Campaign not found")
        if (campaign.status or "").lower() != CampaignStatus.PAUSED.value:
            raise ConflictException("Only PAUSED campaigns can be resumed")

        template = (
            await self.db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == campaign.template_id,
                    WhatsAppMessageTemplate.business_id == business_id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not template or (template.status or "").lower() not in {"approved", "active"}:
            raise ForbiddenException("Template is no longer approved")

        phone = (
            await self.db.execute(
                select(WhatsAppPhoneNumber).where(
                    WhatsAppPhoneNumber.business_id == business_id,
                    WhatsAppPhoneNumber.phone_number_id == campaign.phone_number_id,
                    WhatsAppPhoneNumber.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not phone:
            raise ForbiddenException("Phone number is not linked")
        if (phone.status or "").lower() not in {"active"}:
            raise ForbiddenException("Phone number is not healthy")
        if phone.disconnected_at is not None or phone.disabled_at is not None:
            raise ForbiddenException("Phone number is disconnected/disabled")
        if (phone.sending_status or "").lower() == "disabled":
            raise ForbiddenException("Phone number sending is disabled")
        if (phone.quality_rating or "").lower() in {"red", "low"}:
            raise ForbiddenException("Phone number quality rating is too low")

        business = (
            await self.db.execute(
                select(Business).where(Business.id == business_id, Business.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if not business:
            raise NotFoundException("Business not found")
        if (business.billing_status or "").lower() in {"payment_failed", "suspended"}:
            raise ForbiddenException("Insufficient wallet funds / billing blocked")

        old = campaign.status
        campaign.status = CampaignStatus.QUEUED.value
        campaign.paused_at = None
        self.db.add(
            CampaignStatusEvent(
                campaign_id=campaign.id,
                old_status=old,
                new_status=CampaignStatus.QUEUED.value,
                reason=reason or "manual_resume",
            )
        )

        now = datetime.now(timezone.utc)
        jobs = (
            await self.db.execute(
                select(CampaignSendJob).where(
                    CampaignSendJob.campaign_id == campaign.id,
                    CampaignSendJob.business_id == business_id,
                    CampaignSendJob.deleted_at.is_(None),
                    CampaignSendJob.status.in_(["paused", "pending"]),
                )
            )
        ).scalars().all()
        for job in jobs:
            job.status = "pending"
            job.scheduled_at = now
            job.locked_until = None
            job.locked_by = None

        recipients = (
            await self.db.execute(
                select(CampaignRecipient).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.business_id == business_id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.status.in_(["reserved", "queued"]),
                )
            )
        ).scalars().all()
        for rec in recipients:
            rec.next_retry_at = now

        outbox = (
            await self.db.execute(
                select(MessageOutbox).where(
                    MessageOutbox.campaign_id == campaign.id,
                    MessageOutbox.business_id == business_id,
                    MessageOutbox.deleted_at.is_(None),
                    MessageOutbox.status == "pending",
                )
            )
        ).scalars().all()
        for item in outbox:
            item.next_retry_at = now

        await self.db.flush()
        return campaign


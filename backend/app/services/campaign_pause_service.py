from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.domain.status_enums import CampaignStatus
from app.models.business_domains import Campaign, CampaignSendJob, CampaignStatusEvent, MessageOutbox


class CampaignPauseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def pause_campaign(self, *, business_id: UUID, campaign_id: UUID, reason: str | None = None) -> Campaign:
        res = await self.db.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.business_id == business_id,
                Campaign.deleted_at.is_(None),
            ).with_for_update()
        )
        campaign = res.scalar_one_or_none()
        if not campaign:
            raise NotFoundException("Campaign not found")

        current = (campaign.status or "").lower()
        if current == CampaignStatus.PAUSED.value:
            return campaign
        if current not in {
            CampaignStatus.RUNNING.value,
            CampaignStatus.QUEUED.value,
            CampaignStatus.SCHEDULED.value,
        }:
            raise ConflictException("Only RUNNING/QUEUED/SCHEDULED campaigns can be paused")

        campaign.status = CampaignStatus.PAUSED.value
        campaign.paused_at = datetime.now(timezone.utc)
        self.db.add(
            CampaignStatusEvent(
                campaign_id=campaign.id,
                old_status=current,
                new_status=CampaignStatus.PAUSED.value,
                reason=reason or "manual_pause",
            )
        )

        # Mark unsent queued jobs as paused where possible.
        jobs = (
            await self.db.execute(
                select(CampaignSendJob).where(
                    CampaignSendJob.campaign_id == campaign.id,
                    CampaignSendJob.business_id == business_id,
                    CampaignSendJob.deleted_at.is_(None),
                    CampaignSendJob.status.in_(["pending"]),
                )
            )
        ).scalars().all()
        for job in jobs:
            job.status = "paused"

        # Delay unsent outbox items instead of cancelling.
        pending_outbox = (
            await self.db.execute(
                select(MessageOutbox).where(
                    MessageOutbox.campaign_id == campaign.id,
                    MessageOutbox.business_id == business_id,
                    MessageOutbox.deleted_at.is_(None),
                    MessageOutbox.status == "pending",
                )
            )
        ).scalars().all()
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        for item in pending_outbox:
            item.next_retry_at = retry_at

        await self.db.flush()
        return campaign


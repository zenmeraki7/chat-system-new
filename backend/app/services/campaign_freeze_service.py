from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ForbiddenException
from app.models.business_domains import Campaign, CampaignRecipientSnapshot


class CampaignFreezeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def assert_frozen_snapshot(self, business_id: UUID, campaign_id: UUID):
        campaign_res = await self.db.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.business_id == business_id,
                Campaign.deleted_at.is_(None),
            )
        )
        campaign = campaign_res.scalar_one_or_none()
        if not campaign:
            raise ForbiddenException("Campaign not found for business")

        snapshot_res = await self.db.execute(
            select(CampaignRecipientSnapshot.id).where(
                CampaignRecipientSnapshot.campaign_id == campaign_id,
                CampaignRecipientSnapshot.deleted_at.is_(None),
            )
        )
        if snapshot_res.scalar_one_or_none() is None:
            raise ForbiddenException("Campaign has no frozen recipient snapshot")
        return campaign

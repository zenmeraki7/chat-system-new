from uuid import UUID
from sqlalchemy import update, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.audit_log_service import AuditLogService
from app.services.campaign_state_service import CampaignStateService
from app.models.business import Business
from app.models.business_domains import (
    Campaign,
    BusinessApiKey,
    AutomationFlow,
    OutboxEvent,
)


class BusinessStatusService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditLogService(db)

    async def suspend_business(self, business_id: UUID, reason: str, actor_user_id: UUID | None):
        await self.db.execute(
            update(Business)
            .where(Business.id == business_id)
            .values(status="suspended")
        )
        campaign_state = CampaignStateService(self.db)
        campaigns = (
            await self.db.execute(
                select(Campaign).where(
                    Campaign.business_id == business_id,
                    Campaign.deleted_at.is_(None),
                    Campaign.status.in_(["scheduled", "queued", "running"]),
                )
            )
        ).scalars().all()
        for campaign in campaigns:
            await campaign_state.transition_campaign(
                business_id=business_id,
                campaign_id=campaign.id,
                new_status="paused",
                reason="business_suspended",
            )
        await self.db.execute(
            update(BusinessApiKey)
            .where(BusinessApiKey.business_id == business_id, BusinessApiKey.revoked_at.is_(None))
            .values(disabled_at=func.now())
        )
        await self.db.execute(
            update(AutomationFlow)
            .where(AutomationFlow.business_id == business_id)
            .values(status="paused")
        )
        self.db.add(
            OutboxEvent(
                business_id=business_id,
                event_type="business.suspended",
                payload_json={"reason": reason, "actor_user_id": str(actor_user_id) if actor_user_id else None},
                status="pending",
            )
        )
        await self.audit.write(
            action="business.suspend",
            resource_type="business",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="user" if actor_user_id else "system",
            actor_id=str(actor_user_id) if actor_user_id else None,
            resource_id=str(business_id),
            details={"reason": reason},
        )
        await self.db.commit()

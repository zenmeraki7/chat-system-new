from __future__ import annotations

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.domain.status_enums import CampaignStatus, CampaignRecipientStatus
from app.models.business_domains import (
    Campaign,
    CampaignRecipientSnapshotItem,
    CampaignRecipient,
    CampaignRecipientEvent,
    CampaignStatusEvent,
)


_CAMPAIGN_TRANSITIONS: dict[str, set[str]] = {
    CampaignStatus.DRAFT.value: {CampaignStatus.VALIDATING.value, CampaignStatus.CANCELLED.value},
    CampaignStatus.VALIDATING.value: {
        CampaignStatus.READY.value,
        CampaignStatus.FAILED.value,
        CampaignStatus.CANCELLED.value,
    },
    CampaignStatus.READY.value: {
        CampaignStatus.SCHEDULED.value,
        CampaignStatus.QUEUED.value,
        CampaignStatus.CANCELLED.value,
    },
    CampaignStatus.SCHEDULED.value: {
        CampaignStatus.QUEUED.value,
        CampaignStatus.PAUSED.value,
        CampaignStatus.CANCELLED.value,
    },
    CampaignStatus.QUEUED.value: {
        CampaignStatus.RUNNING.value,
        CampaignStatus.PAUSED.value,
        CampaignStatus.CANCELLED.value,
        CampaignStatus.FAILED.value,
    },
    CampaignStatus.RUNNING.value: {
        CampaignStatus.PAUSED.value,
        CampaignStatus.COMPLETED.value,
        CampaignStatus.COMPLETED_WITH_FAILURES.value,
        CampaignStatus.CANCELLED.value,
        CampaignStatus.FAILED.value,
    },
    CampaignStatus.PAUSED.value: {
        CampaignStatus.QUEUED.value,
        CampaignStatus.RUNNING.value,
        CampaignStatus.CANCELLED.value,
        CampaignStatus.FAILED.value,
    },
    CampaignStatus.COMPLETED.value: set(),
    CampaignStatus.COMPLETED_WITH_FAILURES.value: set(),
    CampaignStatus.CANCELLED.value: set(),
    CampaignStatus.FAILED.value: set(),
}


_RECIPIENT_TRANSITIONS: dict[str, set[str]] = {
    CampaignRecipientStatus.PENDING.value: {
        CampaignRecipientStatus.ELIGIBLE.value,
        CampaignRecipientStatus.SKIPPED.value,
        CampaignRecipientStatus.CANCELLED.value,
        CampaignRecipientStatus.FAILED.value,
    },
    CampaignRecipientStatus.ELIGIBLE.value: {
        CampaignRecipientStatus.RESERVED.value,
        CampaignRecipientStatus.SKIPPED.value,
        CampaignRecipientStatus.CANCELLED.value,
        CampaignRecipientStatus.FAILED.value,
    },
    CampaignRecipientStatus.RESERVED.value: {
        CampaignRecipientStatus.QUEUED.value,
        CampaignRecipientStatus.SKIPPED.value,
        CampaignRecipientStatus.CANCELLED.value,
        CampaignRecipientStatus.FAILED.value,
    },
    CampaignRecipientStatus.QUEUED.value: {
        CampaignRecipientStatus.SENDING.value,
        CampaignRecipientStatus.CANCELLED.value,
        CampaignRecipientStatus.FAILED.value,
    },
    CampaignRecipientStatus.SENDING.value: {
        CampaignRecipientStatus.SENT.value,
        CampaignRecipientStatus.FAILED.value,
        CampaignRecipientStatus.CANCELLED.value,
    },
    CampaignRecipientStatus.SENT.value: {
        CampaignRecipientStatus.DELIVERED.value,
        CampaignRecipientStatus.FAILED.value,
    },
    CampaignRecipientStatus.DELIVERED.value: {
        CampaignRecipientStatus.READ.value,
        CampaignRecipientStatus.REPLIED.value,
        CampaignRecipientStatus.FAILED.value,
    },
    CampaignRecipientStatus.READ.value: {CampaignRecipientStatus.REPLIED.value},
    CampaignRecipientStatus.REPLIED.value: set(),
    CampaignRecipientStatus.FAILED.value: set(),
    CampaignRecipientStatus.SKIPPED.value: set(),
    CampaignRecipientStatus.CANCELLED.value: set(),
}

_WEBHOOK_OWNED_RECIPIENT_STATUSES = {
    CampaignRecipientStatus.SENT.value,
    CampaignRecipientStatus.DELIVERED.value,
    CampaignRecipientStatus.READ.value,
    CampaignRecipientStatus.REPLIED.value,
}


class CampaignStateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def transition_campaign(
        self,
        *,
        business_id: UUID,
        campaign_id: UUID,
        new_status: str,
        reason: str | None = None,
    ) -> Campaign:
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
        old_status = (campaign.status or "").lower()
        target = (new_status or "").lower()
        if old_status == target:
            return campaign
        allowed = _CAMPAIGN_TRANSITIONS.get(old_status)
        if allowed is None or target not in allowed:
            raise ConflictException(f"Invalid campaign transition {old_status} -> {target}")
        campaign.status = target
        self.db.add(
            CampaignStatusEvent(
                campaign_id=campaign.id,
                old_status=old_status,
                new_status=target,
                reason=reason,
            )
        )
        await self.db.flush()
        return campaign

    async def get_campaign_with_allowed_next(self, *, business_id: UUID, campaign_id: UUID) -> tuple[Campaign, list[str]]:
        res = await self.db.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.business_id == business_id,
                Campaign.deleted_at.is_(None),
            )
        )
        campaign = res.scalar_one_or_none()
        if not campaign:
            raise NotFoundException("Campaign not found")
        current = (campaign.status or "").lower()
        return campaign, sorted(_CAMPAIGN_TRANSITIONS.get(current, set()))

    async def transition_recipient_item(
        self,
        *,
        recipient_item_id: UUID,
        new_status: str,
    ) -> CampaignRecipientSnapshotItem:
        res = await self.db.execute(
            select(CampaignRecipientSnapshotItem).where(
                CampaignRecipientSnapshotItem.id == recipient_item_id,
                CampaignRecipientSnapshotItem.deleted_at.is_(None),
            ).with_for_update()
        )
        item = res.scalar_one_or_none()
        if not item:
            raise NotFoundException("Campaign recipient snapshot item not found")
        old_status = (item.status or "").lower()
        target = (new_status or "").lower()
        if old_status == target:
            return item
        if old_status in _WEBHOOK_OWNED_RECIPIENT_STATUSES or target in _WEBHOOK_OWNED_RECIPIENT_STATUSES:
            raise ConflictException(
                "Recipient item statuses sent/delivered/read/replied are webhook-owned and cannot be transitioned manually"
            )
        allowed = _RECIPIENT_TRANSITIONS.get(old_status)
        if allowed is None or target not in allowed:
            raise ConflictException(f"Invalid campaign recipient transition {old_status} -> {target}")
        item.status = target
        await self.db.flush()
        return item

    async def get_snapshot_item_with_allowed_next(self, *, recipient_item_id: UUID) -> tuple[CampaignRecipientSnapshotItem, list[str]]:
        res = await self.db.execute(
            select(CampaignRecipientSnapshotItem).where(
                CampaignRecipientSnapshotItem.id == recipient_item_id,
                CampaignRecipientSnapshotItem.deleted_at.is_(None),
            )
        )
        item = res.scalar_one_or_none()
        if not item:
            raise NotFoundException("Campaign recipient snapshot item not found")
        current = (item.status or "").lower()
        allowed = set(_RECIPIENT_TRANSITIONS.get(current, set()))
        allowed = {status for status in allowed if status not in _WEBHOOK_OWNED_RECIPIENT_STATUSES}
        return item, sorted(allowed)

    async def transition_campaign_recipient(
        self,
        *,
        business_id: UUID,
        campaign_id: UUID,
        campaign_recipient_id: UUID,
        new_status: str,
    ) -> CampaignRecipient:
        res = await self.db.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.id == campaign_recipient_id,
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.business_id == business_id,
                CampaignRecipient.deleted_at.is_(None),
            ).with_for_update()
        )
        recipient = res.scalar_one_or_none()
        if not recipient:
            raise NotFoundException("Campaign recipient not found")
        old_status = (recipient.status or "").lower()
        target = (new_status or "").lower()
        if old_status == target:
            return recipient
        if old_status in _WEBHOOK_OWNED_RECIPIENT_STATUSES or target in _WEBHOOK_OWNED_RECIPIENT_STATUSES:
            raise ConflictException(
                "Recipient statuses sent/delivered/read/replied are webhook-owned and cannot be transitioned manually"
            )
        allowed = _RECIPIENT_TRANSITIONS.get(old_status)
        if allowed is None or target not in allowed:
            raise ConflictException(f"Invalid campaign recipient transition {old_status} -> {target}")
        recipient.status = target
        self.db.add(
            CampaignRecipientEvent(
                campaign_id=campaign_id,
                campaign_recipient_id=recipient.id,
                business_id=business_id,
                event_type="campaign_recipient.status.changed",
                old_status=old_status,
                new_status=target,
                provider_message_id=recipient.provider_message_id,
                payload_json={
                    "campaign_recipient_id": str(recipient.id),
                    "from": old_status,
                    "to": target,
                },
            )
        )
        await self.db.flush()
        return recipient

    async def get_campaign_recipient_with_allowed_next(
        self,
        *,
        business_id: UUID,
        campaign_id: UUID,
        campaign_recipient_id: UUID,
    ) -> tuple[CampaignRecipient, list[str]]:
        res = await self.db.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.id == campaign_recipient_id,
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.business_id == business_id,
                CampaignRecipient.deleted_at.is_(None),
            )
        )
        recipient = res.scalar_one_or_none()
        if not recipient:
            raise NotFoundException("Campaign recipient not found")
        current = (recipient.status or "").lower()
        allowed = set(_RECIPIENT_TRANSITIONS.get(current, set()))
        allowed = {status for status in allowed if status not in _WEBHOOK_OWNED_RECIPIENT_STATUSES}
        return recipient, sorted(allowed)

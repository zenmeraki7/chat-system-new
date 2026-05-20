from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.domain.status_enums import CampaignStatus
from app.models.business_domains import (
    BillingLedger,
    Campaign,
    CampaignRecipient,
    CampaignRecipientEvent,
    CampaignSendJob,
    CampaignStatusEvent,
    MessageOutbox,
    OutboxEvent,
)


class CampaignCancelService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def cancel_campaign(self, *, business_id: UUID, campaign_id: UUID, reason: str | None = None) -> Campaign:
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

        current = (campaign.status or "").lower()
        if current in {CampaignStatus.COMPLETED.value, CampaignStatus.COMPLETED_WITH_FAILURES.value, CampaignStatus.FAILED.value, CampaignStatus.CANCELLED.value}:
            if current == CampaignStatus.CANCELLED.value:
                return campaign
            raise ConflictException("Completed/failed campaigns cannot be cancelled")

        campaign.status = CampaignStatus.CANCELLED.value
        campaign.cancelled_at = datetime.now(timezone.utc)
        self.db.add(
            CampaignStatusEvent(
                campaign_id=campaign.id,
                old_status=current,
                new_status=CampaignStatus.CANCELLED.value,
                reason=reason or "manual_cancel",
            )
        )

        # Stop future sends: cancel pending outbox rows only; keep already sent/sending history untouched.
        outbox_rows = (
            await self.db.execute(
                select(MessageOutbox).where(
                    MessageOutbox.campaign_id == campaign.id,
                    MessageOutbox.business_id == business_id,
                    MessageOutbox.deleted_at.is_(None),
                    MessageOutbox.status == "pending",
                )
            )
        ).scalars().all()
        for row in outbox_rows:
            row.status = "cancelled"
            row.error_code = "campaign_cancelled"
            row.error_message = "Campaign cancelled before send"

        # Mark unsent job queue entries as cancelled.
        jobs = (
            await self.db.execute(
                select(CampaignSendJob).where(
                    CampaignSendJob.campaign_id == campaign.id,
                    CampaignSendJob.business_id == business_id,
                    CampaignSendJob.deleted_at.is_(None),
                    CampaignSendJob.status.in_(["pending", "paused"]),
                )
            )
        ).scalars().all()
        for job in jobs:
            job.status = "cancelled"
            job.failed_at = datetime.now(timezone.utc)

        # Recipient handling rules:
        # PENDING/QUEUED/RESERVED -> CANCELLED
        # SENDING -> keep (uncertain/in-flight)
        # SENT/DELIVERED/READ/FAILED -> keep as-is
        recipients = (
            await self.db.execute(
                select(CampaignRecipient).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.business_id == business_id,
                    CampaignRecipient.deleted_at.is_(None),
                ).with_for_update()
            )
        ).scalars().all()

        for rec in recipients:
            old_status = (rec.status or "").lower()
            if old_status in {"pending", "queued", "reserved"}:
                rec.status = "cancelled"
                self.db.add(
                    CampaignRecipientEvent(
                        campaign_id=campaign.id,
                        campaign_recipient_id=rec.id,
                        business_id=business_id,
                        event_type="campaign_recipient.cancelled_by_campaign",
                        old_status=old_status,
                        new_status="cancelled",
                        provider_message_id=rec.provider_message_id,
                        payload_json={"reason": reason or "manual_cancel"},
                    )
                )
                # Billing: release holds for unsent recipients.
                hold_amount = float(rec.reserved_amount or 0.0)
                if hold_amount > 0:
                    self.db.add(
                        BillingLedger(
                            business_id=business_id,
                            campaign_id=campaign.id,
                            campaign_recipient_id=rec.id,
                            message_outbox_id=None,
                            provider_message_id=None,
                            entry_type="release",
                            amount=hold_amount,
                            currency="USD",
                            status="posted",
                            reason="campaign_cancel_unsent_release",
                            metadata_json={"recipient_status": old_status},
                        )
                    )

        self.db.add(
            OutboxEvent(
                business_id=business_id,
                campaign_id=campaign.id,
                operation_id=f"campaign:{campaign.id}:finalize:cancel",
                event_type="campaign.finalize",
                payload_json={"campaign_id": str(campaign.id), "source": "cancel_event"},
                status="pending",
            )
        )

        await self.db.flush()
        return campaign

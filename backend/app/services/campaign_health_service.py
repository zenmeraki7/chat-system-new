from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import Campaign, CampaignRecipient, ContactSource, WhatsAppPhoneNumber


class CampaignHealthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_health(self, *, business_id: UUID, campaign_id: UUID) -> dict:
        campaign = (
            await self.db.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id,
                    Campaign.business_id == business_id,
                    Campaign.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if campaign is None:
            raise ValueError("Campaign not found")

        total = int(campaign.total_recipients or 0)
        sent = int(campaign.sent_count or 0)
        delivered = int(campaign.delivered_count or 0)
        read = int(campaign.read_count or 0)
        replied = int(campaign.replied_count or 0)
        failed = int(campaign.failed_count or 0)

        delivery_rate = (delivered / max(1, sent)) if sent else 0.0
        read_rate = (read / max(1, delivered)) if delivered else 0.0
        reply_rate = (replied / max(1, read)) if read else 0.0
        failure_rate = (failed / max(1, sent)) if sent else 0.0

        recent_window = datetime.now(timezone.utc) - timedelta(minutes=15)
        unsub_recent = (
            await self.db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.business_id == business_id,
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.updated_at >= recent_window,
                    (
                        CampaignRecipient.eligibility_reason.ilike("%opted_out%")
                        | CampaignRecipient.eligibility_reason.ilike("%unsubscribed%")
                    ),
                )
            )
        ).scalar_one()
        unsubscribe_rate = (float(unsub_recent or 0) / float(max(1, total))) if total else 0.0

        phone = (
            await self.db.execute(
                select(WhatsAppPhoneNumber).where(
                    WhatsAppPhoneNumber.business_id == business_id,
                    WhatsAppPhoneNumber.phone_number_id == campaign.phone_number_id,
                    WhatsAppPhoneNumber.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        phone_quality = (phone.quality_rating or "unknown").lower() if phone else "unknown"

        estimated_cost = float(campaign.estimated_cost or 0.0)
        actual_cost = float(campaign.actual_cost or 0.0)
        cost_burn_ratio = (actual_cost / max(estimated_cost, 1.0)) if estimated_cost > 0 else 0.0

        score = 100
        score -= min(35, int(failure_rate * 140))
        score -= min(18, int(unsubscribe_rate * 200))
        score -= min(12, int(max(0.0, 0.45 - delivery_rate) * 40))
        score -= min(10, int(max(0.0, 1.10 - max(0.01, read_rate)) * 8))
        if cost_burn_ratio > 1.20:
            score -= 8
        if phone_quality in {"red", "low"}:
            score -= 20
        elif phone_quality == "yellow":
            score -= 8
        score = max(0, min(100, score))

        def band(val: float, good: float, warn: float) -> str:
            if val >= good:
                return "Good"
            if val >= warn:
                return "Normal"
            return "Risky"

        breakdown = {
            "delivery": band(delivery_rate, 0.75, 0.55),
            "read_rate": band(read_rate, 0.45, 0.25),
            "reply_rate": band(reply_rate, 0.20, 0.08),
            "unsubscribe": "Low" if unsubscribe_rate < 0.01 else ("Normal" if unsubscribe_rate < 0.03 else "High"),
            "failure_rate": "Safe" if failure_rate < 0.08 else ("Watch" if failure_rate < 0.14 else "High"),
            "cost_burn": "On track" if cost_burn_ratio <= 1.1 else "Over burn",
            "phone_quality": "Stable" if phone_quality in {"green", "high", "unknown"} else "Degrading",
        }

        risks: list[str] = []
        suggested_action: str | None = None

        imported_contact_ids = (
            await self.db.execute(
                select(ContactSource.contact_id).where(
                    ContactSource.business_id == business_id,
                    ContactSource.source.in_(["csv_import", "import", "bulk_import"]),
                    ContactSource.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        imported_fail_rate = 0.0
        if imported_contact_ids:
            imported_total = (
                await self.db.execute(
                    select(func.count(CampaignRecipient.id)).where(
                        CampaignRecipient.business_id == business_id,
                        CampaignRecipient.campaign_id == campaign_id,
                        CampaignRecipient.contact_id.in_(imported_contact_ids),
                        CampaignRecipient.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
            imported_failed = (
                await self.db.execute(
                    select(func.count(CampaignRecipient.id)).where(
                        CampaignRecipient.business_id == business_id,
                        CampaignRecipient.campaign_id == campaign_id,
                        CampaignRecipient.contact_id.in_(imported_contact_ids),
                        CampaignRecipient.deleted_at.is_(None),
                        CampaignRecipient.status == "failed",
                    )
                )
            ).scalar_one()
            if imported_total:
                imported_fail_rate = float(imported_failed or 0) / float(imported_total)

        if failure_rate >= 0.14 and imported_fail_rate >= 0.12:
            risks.append("Failure rate is high for recently imported contacts.")
            suggested_action = "Pause cold audience batch."
        elif failure_rate >= 0.14:
            risks.append("Failure rate is high.")
            suggested_action = "Pause and resume slowly."
        elif unsubscribe_rate >= 0.03:
            risks.append("Unsubscribe rate is elevated.")
            suggested_action = "Exclude risky/suppressed audience."
        elif phone_quality in {"red", "low"}:
            risks.append("Phone quality is degrading.")
            suggested_action = "Pause marketing sends."

        return {
            "campaign_id": str(campaign_id),
            "campaign_health_score": score,
            "health_label": f"{score}/100",
            "breakdown": breakdown,
            "metrics": {
                "delivery_rate": round(delivery_rate, 4),
                "read_rate": round(read_rate, 4),
                "reply_rate": round(reply_rate, 4),
                "unsubscribe_rate": round(unsubscribe_rate, 4),
                "failure_rate": round(failure_rate, 4),
                "cost_burn_ratio": round(cost_burn_ratio, 4),
                "imported_contact_failure_rate": round(imported_fail_rate, 4),
            },
            "risk_detected": risks,
            "suggested_action": suggested_action,
        }

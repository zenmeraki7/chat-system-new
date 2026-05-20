from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import CampaignRecipient, Contact, ContactSource


class AudienceWarmthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _days_since(ts: datetime | None) -> int | None:
        if ts is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - ts).total_seconds() // 86400))

    async def score_campaign_audience(self, *, business_id: UUID, campaign_id: UUID) -> dict:
        rows = (
            await self.db.execute(
                select(CampaignRecipient, Contact)
                .outerjoin(Contact, Contact.id == CampaignRecipient.contact_id)
                .where(
                    CampaignRecipient.business_id == business_id,
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.deleted_at.is_(None),
                )
            )
        ).all()

        contact_ids = [c.id for _, c in rows if c is not None]
        historical: dict[UUID, dict[str, int]] = defaultdict(lambda: {"sends": 0, "reads": 0, "replies": 0, "ignored": 0})
        if contact_ids:
            past = (
                await self.db.execute(
                    select(CampaignRecipient).where(
                        CampaignRecipient.business_id == business_id,
                        CampaignRecipient.contact_id.in_(contact_ids),
                        CampaignRecipient.campaign_id != campaign_id,
                        CampaignRecipient.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            for p in past:
                if p.contact_id is None:
                    continue
                h = historical[p.contact_id]
                if (p.status or "").lower() in {"sent", "delivered", "read", "replied", "failed"}:
                    h["sends"] += 1
                if p.read_at is not None or (p.status or "").lower() == "read":
                    h["reads"] += 1
                if p.replied_at is not None or (p.status or "").lower() == "replied":
                    h["replies"] += 1
                if (p.status or "").lower() in {"sent", "delivered"} and p.read_at is None and p.replied_at is None:
                    h["ignored"] += 1

        csv_source_age_days: dict[UUID, int] = {}
        if contact_ids:
            source_rows = (
                await self.db.execute(
                    select(ContactSource).where(
                        ContactSource.business_id == business_id,
                        ContactSource.contact_id.in_(contact_ids),
                        ContactSource.source.in_(["csv_import", "import", "bulk_import"]),
                        ContactSource.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            latest_source: dict[UUID, datetime] = {}
            for s in source_rows:
                if s.contact_id not in latest_source or s.created_at > latest_source[s.contact_id]:
                    latest_source[s.contact_id] = s.created_at
            for cid, ts in latest_source.items():
                csv_source_age_days[cid] = self._days_since(ts) or 0

        buckets = {"hot": 0, "warm": 0, "cold": 0, "risky": 0, "suppressed": 0}
        for rec, contact in rows:
            reason = (rec.eligibility_reason or "").lower()
            if any(k in reason for k in ["opted_out", "blocked", "missing_consent"]) or (rec.status or "").lower() == "skipped":
                buckets["suppressed"] += 1
                continue

            if contact is None:
                buckets["cold"] += 1
                continue

            hist = historical[contact.id]
            last_inbound_days = self._days_since(contact.last_message_at)
            last_seen_days = self._days_since(contact.last_seen_at)
            csv_age = csv_source_age_days.get(contact.id)
            opted_out_hist = contact.unsubscribed_at is not None

            if opted_out_hist:
                buckets["suppressed"] += 1
            elif hist["ignored"] >= 5 or (hist["sends"] >= 8 and hist["reads"] == 0) or (csv_age is not None and csv_age <= 7 and (last_inbound_days is None or last_inbound_days > 180)):
                buckets["risky"] += 1
            elif (last_inbound_days is not None and last_inbound_days <= 7) or hist["replies"] > 0:
                buckets["hot"] += 1
            elif (last_inbound_days is not None and last_inbound_days <= 30) or hist["reads"] > 0 or (last_seen_days is not None and last_seen_days <= 30):
                buckets["warm"] += 1
            else:
                buckets["cold"] += 1

        total = sum(buckets.values())
        recommendation = [
            "Send to Hot + Warm now.",
            "Use slower rollout for Cold.",
            "Exclude Risky contacts.",
        ]
        return {
            "campaign_id": str(campaign_id),
            "audience_quality": {
                "hot": buckets["hot"],
                "warm": buckets["warm"],
                "cold": buckets["cold"],
                "risky": buckets["risky"],
                "suppressed": buckets["suppressed"],
                "total": total,
            },
            "recommended_action": recommendation,
        }

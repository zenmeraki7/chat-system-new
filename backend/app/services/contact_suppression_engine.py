from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import Campaign, CampaignRecipient, Contact, SuppressionListEntry


SUPPRESSION_REASONS = {
    "OPTED_OUT",
    "INVALID_PHONE",
    "NO_CONSENT",
    "BLOCKED",
    "FREQUENCY_CAP_EXCEEDED",
    "DUPLICATE_ACTIVE_CAMPAIGN",
    "RECENTLY_MESSAGED",
    "MISSING_VARIABLE",
    "UNSUPPORTED_COUNTRY",
}


@dataclass
class SuppressionDecision:
    allowed: bool
    reasons: list[str]


class ContactSuppressionEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate_for_campaign_recipient(
        self,
        *,
        campaign: Campaign,
        phone_e164: str | None,
        contact: Contact | None,
        variables: dict,
        required_vars: list[str],
        country_code: str | None,
        seen_phones: set[str],
    ) -> SuppressionDecision:
        reasons: list[str] = []
        phone = (phone_e164 or "").strip()
        if not phone or not phone.startswith("+") or len(phone) < 8:
            reasons.append("INVALID_PHONE")
            return SuppressionDecision(allowed=False, reasons=self._dedupe(reasons))

        if phone in seen_phones:
            reasons.append("DUPLICATE_ACTIVE_CAMPAIGN")
        else:
            seen_phones.add(phone)

        cc = (country_code or "").strip().upper()
        if cc and (len(cc) != 2 or not cc.isalpha()):
            reasons.append("UNSUPPORTED_COUNTRY")

        if contact is not None:
            opt_in = (contact.opt_in_status or "").lower()
            if opt_in != "opted_in":
                reasons.append("NO_CONSENT")
            if opt_in in {"opted_out", "unsubscribed"} or contact.unsubscribed_at is not None:
                reasons.append("OPTED_OUT")
            if contact.blocked_at is not None:
                reasons.append("BLOCKED")
            if contact.last_message_at is not None and contact.last_message_at >= (datetime.now(timezone.utc) - timedelta(hours=24)):
                reasons.append("RECENTLY_MESSAGED")
            if await self._is_frequency_cap_exceeded(campaign.business_id, contact, phone):
                reasons.append("FREQUENCY_CAP_EXCEEDED")
        else:
            reasons.append("NO_CONSENT")

        if await self._is_blocklisted(campaign.business_id, contact, phone):
            reasons.append("BLOCKED")
        if await self._is_duplicate_active_campaign(campaign.id, campaign.business_id, phone):
            reasons.append("DUPLICATE_ACTIVE_CAMPAIGN")

        for var in required_vars:
            val = (variables or {}).get(var)
            if val is None or (isinstance(val, str) and not val.strip()):
                reasons.append("MISSING_VARIABLE")
                break

        reasons = self._dedupe(reasons)
        return SuppressionDecision(allowed=len(reasons) == 0, reasons=reasons)

    async def _is_blocklisted(self, business_id: UUID, contact: Contact | None, phone_e164: str) -> bool:
        hashes = [phone_e164]
        if contact and contact.phone_hash:
            hashes.append(contact.phone_hash)
        row = await self.db.execute(
            select(SuppressionListEntry.id).where(
                SuppressionListEntry.business_id == business_id,
                SuppressionListEntry.identity_hash.in_(hashes),
                SuppressionListEntry.deleted_at.is_(None),
            ).limit(1)
        )
        return row.scalar_one_or_none() is not None

    async def _is_duplicate_active_campaign(self, campaign_id: UUID, business_id: UUID, phone_e164: str) -> bool:
        row = await self.db.execute(
            select(CampaignRecipient.id).where(
                CampaignRecipient.business_id == business_id,
                CampaignRecipient.campaign_id != campaign_id,
                CampaignRecipient.phone_e164 == phone_e164,
                CampaignRecipient.deleted_at.is_(None),
                CampaignRecipient.status.in_(["pending", "queued", "sending", "unknown_retryable"]),
            ).limit(1)
        )
        return row.scalar_one_or_none() is not None

    async def _is_frequency_cap_exceeded(self, business_id: UUID, contact: Contact, phone_e164: str) -> bool:
        # Lightweight pre-check for recent messaging load before queueing campaign sends.
        # Final enforcement remains in ContactFrequencyService at send time.
        key_phone = phone_e164
        row = await self.db.execute(
            select(CampaignRecipient.id).where(
                CampaignRecipient.business_id == business_id,
                CampaignRecipient.deleted_at.is_(None),
                CampaignRecipient.phone_e164 == key_phone,
                CampaignRecipient.sent_at.is_not(None),
                CampaignRecipient.sent_at >= (datetime.now(timezone.utc) - timedelta(days=1)),
            )
        )
        daily = len(list(row.scalars().all()))
        return daily >= 1

    @staticmethod
    def _dedupe(reasons: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for r in reasons:
            rr = r.strip().upper()
            if rr in SUPPRESSION_REASONS and rr not in seen:
                seen.add(rr)
                out.append(rr)
        return out


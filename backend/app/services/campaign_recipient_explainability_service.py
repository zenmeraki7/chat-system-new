from __future__ import annotations

from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import Campaign, CampaignRecipient, MessageOutbox, WhatsAppMessageTemplate


class CampaignRecipientExplainabilityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _parse_eligibility_reason(reason: str | None) -> list[str]:
        if not reason:
            return []
        parts = [p.strip() for p in reason.split(",") if p.strip()]
        friendly: list[str] = []
        for p in parts:
            if p == "opted_out_contact":
                friendly.append("Contact is opted out")
            elif p == "blocked_contact":
                friendly.append("Contact is blocked")
            elif p == "invalid_phone":
                friendly.append("Phone number is invalid or not E.164")
            elif p == "duplicate_phone":
                friendly.append("Duplicate phone in campaign recipient set")
            elif p == "missing_consent":
                friendly.append("Missing consent/opt-in for messaging")
            elif p.startswith("missing_required_template_variable:"):
                var = p.split(":", 1)[1]
                friendly.append(f"Template requires variable {var} but recipient has no value")
            else:
                friendly.append(p.replace("_", " "))
        return friendly

    async def explain_recipient(
        self,
        *,
        business_id: UUID,
        campaign_id: UUID,
        recipient: CampaignRecipient,
    ) -> dict:
        campaign = (
            await self.db.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id,
                    Campaign.business_id == business_id,
                    Campaign.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        template_required_vars: list[str] = []
        if campaign.template_id:
            template = (
                await self.db.execute(
                    select(WhatsAppMessageTemplate).where(
                        WhatsAppMessageTemplate.id == campaign.template_id,
                        WhatsAppMessageTemplate.business_id == business_id,
                        WhatsAppMessageTemplate.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if template:
                required = (template.components_json or {}).get("required_variables")
                if isinstance(required, list):
                    template_required_vars = [str(v) for v in required if str(v).strip()]

        outbox = (
            await self.db.execute(
                select(MessageOutbox)
                .where(
                    MessageOutbox.business_id == business_id,
                    MessageOutbox.campaign_id == campaign_id,
                    MessageOutbox.campaign_recipient_id == recipient.id,
                    MessageOutbox.deleted_at.is_(None),
                )
                .order_by(MessageOutbox.created_at.desc(), MessageOutbox.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        reasons: list[str] = []
        status = (recipient.status or "").lower()
        category = (campaign.template_category or "").lower()

        if status == "skipped":
            reasons.extend(self._parse_eligibility_reason(recipient.eligibility_reason))
            if any("opted out" in r.lower() for r in reasons) and category == "marketing":
                reasons.append("Suppression rule applied: marketing send blocked after opt-out")
        elif status == "failed":
            if recipient.last_error_message:
                reasons.append(f"Provider/API error: {recipient.last_error_message}")
            elif recipient.last_error_code:
                reasons.append(f"Provider/API error code: {recipient.last_error_code}")
            else:
                reasons.append("Send failed at provider/runtime")
        elif status in {"queued", "reserved", "pending"}:
            if outbox and outbox.next_retry_at is not None:
                local_ts = outbox.next_retry_at.astimezone(timezone.utc).isoformat()
                reasons.append(f"Delayed by retry/backoff window until {local_ts}")
            else:
                reasons.append("Waiting in queue for dispatch/send")
        elif status in {"sent", "delivered", "read"}:
            reasons.append(f"Recipient currently at status '{status}'")

        variables = recipient.variables_json or {}
        missing_required = [var for var in template_required_vars if variables.get(var) in (None, "")]
        for var in missing_required:
            reasons.append(f"Template requires variable {var}; recipient has no mapped value")

        if not reasons:
            reasons.append("No explicit blocking reason recorded")

        return {
            "recipient_id": str(recipient.id),
            "status": recipient.status,
            "eligibility_status": recipient.eligibility_status,
            "explainability_reasons": reasons,
            "provider_message_id": recipient.provider_message_id,
            "last_error_code": recipient.last_error_code,
            "last_error_message": recipient.last_error_message,
            "next_retry_at": outbox.next_retry_at.isoformat() if outbox and outbox.next_retry_at else None,
        }

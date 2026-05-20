from __future__ import annotations

import re
import uuid
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException
from app.models.business_domains import (
    Campaign,
    CampaignRecipient,
    Contact,
    PhoneNumberAssignment,
    WhatsAppMessageTemplate,
    WhatsAppPhoneNumber,
)


class CampaignService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_draft_campaign(
        self,
        *,
        business_id: UUID,
        created_by_user_id: UUID | None,
        name: str,
        phone_number_id: str,
        template_id: UUID,
        segment_id: UUID | None,
        csv_import_id: UUID | None,
        scheduled_at,
        campaign_type: str,
    ) -> Campaign:
        phone = (
            await self.db.execute(
                select(WhatsAppPhoneNumber).where(
                    WhatsAppPhoneNumber.business_id == business_id,
                    WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                    WhatsAppPhoneNumber.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not phone:
            raise ForbiddenException("phone_number_id is not owned by this business")

        assignment = (
            await self.db.execute(
                select(PhoneNumberAssignment).where(
                    PhoneNumberAssignment.business_id == business_id,
                    PhoneNumberAssignment.phone_number_id == phone_number_id,
                    PhoneNumberAssignment.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        waba_id = assignment.waba_id if assignment else None

        template = (
            await self.db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == template_id,
                    WhatsAppMessageTemplate.business_id == business_id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not template:
            raise ForbiddenException("template_id does not belong to this business")
        if waba_id and template.waba_id != waba_id:
            raise ForbiddenException("template does not belong to the selected phone number WABA")
        if (template.status or "").lower() not in {"approved", "active"}:
            raise BadRequestException("template is not approved")
        if not (template.language or "").strip():
            raise BadRequestException("template language is missing")

        row = Campaign(
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            public_id=f"cmp_{uuid.uuid4().hex[:12]}",
            name=name.strip(),
            type=campaign_type,
            status="draft",
            template_id=template.id,
            template_name=template.name,
            template_language=template.language,
            template_category=template.category,
            segment_id=segment_id,
            csv_import_id=csv_import_id,
            scheduled_at=scheduled_at,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    @staticmethod
    def _extract_placeholders(template: WhatsAppMessageTemplate) -> list[str]:
        placeholders: set[str] = set()
        components = template.components_json or {}
        texts: list[str] = []
        if isinstance(components, dict):
            if isinstance(components.get("body_text"), str):
                texts.append(components["body_text"])
            comp_list = components.get("components")
            if isinstance(comp_list, list):
                for c in comp_list:
                    if isinstance(c, dict) and isinstance(c.get("text"), str):
                        texts.append(c["text"])
        for txt in texts:
            for ph in re.findall(r"\{\{\d+\}\}", txt):
                placeholders.add(ph)
        return sorted(placeholders)

    @staticmethod
    def _required_media_header_kind(template: WhatsAppMessageTemplate) -> str | None:
        components = template.components_json or {}
        comp_list = components.get("components") if isinstance(components, dict) else None
        if not isinstance(comp_list, list):
            return None
        for c in comp_list:
            if not isinstance(c, dict):
                continue
            if str(c.get("type") or "").upper() != "HEADER":
                continue
            fmt = str(c.get("format") or "").lower()
            if fmt in {"image", "video", "document"}:
                return fmt
        return None

    @staticmethod
    def _allowed_categories_for_campaign_type(campaign_type: str) -> set[str]:
        c = (campaign_type or "").lower()
        if c == "broadcast":
            return {"marketing", "utility"}
        if c == "abandoned_cart":
            return {"utility"}
        if c in {"automation", "followup"}:
            return {"utility", "authentication"}
        return {"marketing", "utility", "authentication"}

    async def set_variable_mapping(
        self,
        *,
        business_id: UUID,
        campaign_id: UUID,
        variable_mapping: dict[str, str],
    ) -> Campaign:
        campaign = (
            await self.db.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id,
                    Campaign.business_id == business_id,
                    Campaign.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not campaign:
            raise BadRequestException("Campaign not found")
        template = (
            await self.db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == campaign.template_id,
                    WhatsAppMessageTemplate.business_id == business_id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not template:
            raise BadRequestException("Template not found for campaign")
        expected = self._extract_placeholders(template)
        missing = [ph for ph in expected if ph not in (variable_mapping or {})]
        if missing:
            raise BadRequestException(f"Missing variable mapping(s): {', '.join(missing)}")
        campaign.variable_mapping_json = dict(variable_mapping or {})
        self.invalidate_preview(campaign)
        await self.db.flush()
        return campaign

    @staticmethod
    def invalidate_preview(campaign: Campaign) -> None:
        campaign.preview_hash = None
        campaign.campaign_config_hash = CampaignService.compute_campaign_config_hash(campaign)
        campaign.preview_invalidated_at = datetime.now(timezone.utc)

    @staticmethod
    def compute_campaign_config_hash(campaign: Campaign) -> str:
        material = {
            "campaign_id": str(campaign.id),
            "name": campaign.name,
            "template_id": str(campaign.template_id) if campaign.template_id else None,
            "template_name": campaign.template_name,
            "template_language": campaign.template_language,
            "template_category": campaign.template_category,
            "phone_number_id": campaign.phone_number_id,
            "segment_id": str(campaign.segment_id) if campaign.segment_id else None,
            "csv_import_id": str(campaign.csv_import_id) if campaign.csv_import_id else None,
            "mapping": campaign.variable_mapping_json or {},
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _resolve(contact: Contact | None, expr: str | None):
        if not expr:
            return None
        expr = expr.strip()
        if expr.startswith("static:"):
            return expr.split("static:", 1)[1]
        if expr.startswith("contact.") and contact:
            key = expr.split("contact.", 1)[1]
            if key == "first_name":
                return (contact.display_name or "").split(" ")[0] if contact.display_name else None
            mapping = {
                "name": contact.display_name,
                "phone_e164": contact.normalized_phone,
                "wa_id": contact.wa_id,
                "email": contact.email,
            }
            return mapping.get(key)
        if expr.startswith("custom.") and contact:
            key = expr.split("custom.", 1)[1]
            return (contact.custom_attributes or {}).get(key)
        return None

    async def validate_template_mapping_for_campaign(self, *, business_id: UUID, campaign_id: UUID) -> list[dict]:
        campaign = (
            await self.db.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id,
                    Campaign.business_id == business_id,
                    Campaign.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not campaign:
            raise BadRequestException("Campaign not found")
        template = (
            await self.db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == campaign.template_id,
                    WhatsAppMessageTemplate.business_id == business_id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not template:
            raise BadRequestException("Template not found")

        errors: list[dict] = []
        status = (template.status or "").lower()
        if status in {"rejected", "paused"}:
            errors.append({"scope": "template", "error": f"{status}_template"})
        if (campaign.template_language or "").strip() and campaign.template_language != template.language:
            errors.append({"scope": "template", "error": "wrong_language"})
        category = (template.category or "").lower()
        if category and category not in self._allowed_categories_for_campaign_type(campaign.type):
            errors.append({"scope": "template", "error": "wrong_category_for_campaign_type"})

        mapping = dict(campaign.variable_mapping_json or {})
        placeholders = self._extract_placeholders(template)
        for ph in placeholders:
            if ph not in mapping:
                errors.append({"scope": "mapping", "error": "missing_variables", "variable": ph})
            elif not str(mapping.get(ph) or "").strip():
                errors.append({"scope": "mapping", "error": "empty_variables", "variable": ph})
        if self._required_media_header_kind(template):
            if not str(mapping.get("__header_media__") or "").strip():
                errors.append({"scope": "mapping", "error": "wrong_media_header"})

        recipients = (
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
        for rec, contact in recipients:
            for ph in placeholders:
                val = self._resolve(contact, mapping.get(ph))
                if val is None or (isinstance(val, str) and not val.strip()):
                    errors.append(
                        {
                            "scope": "recipient",
                            "campaign_recipient_id": str(rec.id),
                            "error": "missing_variables",
                            "variable": ph,
                        }
                    )
        return errors

    async def preview_campaign(self, *, business_id: UUID, campaign_id: UUID) -> dict:
        campaign = (
            await self.db.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id,
                    Campaign.business_id == business_id,
                    Campaign.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not campaign:
            raise BadRequestException("Campaign not found")
        template = (
            await self.db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == campaign.template_id,
                    WhatsAppMessageTemplate.business_id == business_id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not template:
            raise BadRequestException("Template not found")

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

        total = len(rows)
        eligible = 0
        skipped = 0
        skip_reasons = {
            "opted_out": 0,
            "invalid_phone": 0,
            "missing_variable": 0,
            "duplicate": 0,
            "blocked": 0,
            "missing_consent": 0,
            "other": 0,
        }
        variable_errors = await self.validate_template_mapping_for_campaign(
            business_id=business_id,
            campaign_id=campaign_id,
        )
        variable_error_count = len([e for e in variable_errors if e.get("error") in {"missing_variables", "empty_variables"}])
        recipient_variable_error_ids = {
            e.get("campaign_recipient_id")
            for e in variable_errors
            if e.get("scope") == "recipient" and e.get("campaign_recipient_id")
        }

        by_country: dict[str, int] = {}
        seen_phones: set[str] = set()
        samples: list[dict] = []
        mapping = dict(campaign.variable_mapping_json or {})
        placeholders = self._extract_placeholders(template)
        template_text = None
        components = template.components_json or {}
        if isinstance(components, dict) and isinstance(components.get("body_text"), str):
            template_text = components.get("body_text")

        for rec, contact in rows:
            phone = rec.phone_e164 or ""
            country = "unknown"
            if phone.startswith("+") and len(phone) >= 3:
                country = phone[1:3]
            by_country[country] = by_country.get(country, 0) + 1

            local_skips = []
            normalized = phone if re.match(r"^\+[1-9]\d{6,14}$", phone) else None
            if not normalized:
                local_skips.append("invalid_phone")
            elif normalized in seen_phones:
                local_skips.append("duplicate")
            else:
                seen_phones.add(normalized)

            if contact:
                if (contact.opt_in_status or "").lower() in {"opted_out", "unsubscribed"} or contact.unsubscribed_at is not None:
                    local_skips.append("opted_out")
                if contact.blocked_at is not None:
                    local_skips.append("blocked")
                if (contact.opt_in_status or "").lower() != "opted_in":
                    local_skips.append("missing_consent")
            else:
                if rec.eligibility_status != "eligible":
                    local_skips.append("missing_consent")

            if str(rec.id) in recipient_variable_error_ids:
                local_skips.append("missing_variable")

            if local_skips:
                skipped += 1
                for reason in local_skips:
                    if reason in skip_reasons:
                        skip_reasons[reason] += 1
                    else:
                        skip_reasons["other"] += 1
            else:
                eligible += 1
                if len(samples) < 3:
                    rendered = template_text or ""
                    for ph in placeholders:
                        val = self._resolve(contact, mapping.get(ph))
                        rendered = rendered.replace(ph, str(val or ""))
                    samples.append(
                        {
                            "campaign_recipient_id": str(rec.id),
                            "to_phone_e164": rec.phone_e164,
                            "rendered_text": rendered,
                        }
                    )

        per_recipient_cost = 0.13  # conservative default estimate
        est_amount = round(eligible * per_recipient_cost, 2)
        send_rate_per_min = 600
        est_duration = max(1, (eligible + send_rate_per_min - 1) // send_rate_per_min)
        country_breakdown = [
            {
                "country": c,
                "recipients": n,
                "estimated_amount": round(n * per_recipient_cost, 2),
                "currency": "INR",
            }
            for c, n in sorted(by_country.items(), key=lambda x: x[0])
        ]

        warnings: list[str] = []
        if eligible > 0 and skip_reasons["invalid_phone"] / max(total, 1) > 0.02:
            warnings.append("High invalid-phone rate")
        if eligible > 0 and skip_reasons["opted_out"] / max(total, 1) > 0.05:
            warnings.append("High opted-out population")
        if eligible > 10000:
            warnings.append("Large send volume; review throughput limits")

        preview = {
            "total_recipients": total,
            "eligible_recipients": eligible,
            "skipped_recipients": skipped,
            "skips": {
                "opted_out": skip_reasons["opted_out"],
                "invalid_phone": skip_reasons["invalid_phone"],
                "missing_variable": skip_reasons["missing_variable"],
                "duplicate": skip_reasons["duplicate"],
            },
            "estimated_cost": {"amount": est_amount, "currency": "INR"},
            "estimated_duration_minutes": est_duration,
            "recipient_count": total,
            "eligibility_summary": {
                "eligible": eligible,
                "ineligible": skipped,
                "blocked": skip_reasons["blocked"],
                "missing_consent": skip_reasons["missing_consent"],
            },
            "variable_error_summary": {
                "total_errors": variable_error_count,
                "recipient_errors": len(recipient_variable_error_ids),
            },
            "country_cost_breakdown": country_breakdown,
            "template_category": template.category,
            "template_preview": template_text,
            "sample_rendered_messages": samples,
            "quality_rate_warnings": warnings,
        }
        current_config_hash = self.compute_campaign_config_hash(campaign)
        campaign.preview_hash = current_config_hash
        campaign.campaign_config_hash = current_config_hash
        campaign.preview_generated_at = datetime.now(timezone.utc)
        campaign.preview_invalidated_at = None
        await self.db.flush()
        return preview

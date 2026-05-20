from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.business_domains import (
    Campaign,
    CampaignRecipient,
    Contact,
    ContactImportJob,
    ContactImportRow,
    ConversationSavedView,
    WhatsAppMessageTemplate,
)
from app.services.campaign_state_service import CampaignStateService
from app.services.campaign_service import CampaignService
from app.services.campaign_blackbox_recorder import CampaignBlackBoxRecorder
from app.services.contact_hygiene_service import contact_hygiene_service
from app.services.contact_segment_service import ContactSegmentService
from app.services.contact_suppression_engine import ContactSuppressionEngine
from app.models.business_domains import CampaignRecipientEvent


class CampaignRecipientSourceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.state = CampaignStateService(db)

    async def set_source(
        self,
        *,
        business_id: UUID,
        campaign_id: UUID,
        source_type: str,
        segment_id: UUID | None,
        csv_import_id: UUID | None,
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
            raise NotFoundException("Campaign not found")
        if campaign.status != "draft":
            raise BadRequestException("Recipient source can be set only in DRAFT")
        if source_type == "saved_segment":
            if not segment_id:
                raise BadRequestException("segment_id is required for saved_segment")
            segment = (
                await self.db.execute(
                    select(ConversationSavedView).where(
                        ConversationSavedView.id == segment_id,
                        ConversationSavedView.business_id == business_id,
                        ConversationSavedView.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if not segment:
                raise ForbiddenException("segment_id does not belong to this business")
            campaign.segment_id = segment_id
            campaign.csv_import_id = None
        else:
            if not csv_import_id:
                raise BadRequestException("csv_import_id is required for csv_upload")
            csv_job = (
                await self.db.execute(
                    select(ContactImportJob).where(
                        ContactImportJob.id == csv_import_id,
                        ContactImportJob.business_id == business_id,
                        ContactImportJob.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if not csv_job:
                raise ForbiddenException("csv_import_id does not belong to this business")
            campaign.csv_import_id = csv_import_id
            campaign.segment_id = None
        CampaignService.invalidate_preview(campaign)
        await self.db.flush()
        return campaign

    def _required_template_variables(self, template: WhatsAppMessageTemplate) -> list[str]:
        components = template.components_json or {}
        required = components.get("required_variables")
        if isinstance(required, list):
            return [str(x) for x in required if str(x).strip()]
        return []

    def _validate_row(
        self,
        *,
        phone_e164: str | None,
        country_code: str | None,
        opt_in_status: str | None,
        blocked_at,
        unsubscribed_at,
        variables: dict,
        required_vars: list[str],
        seen_phones: set[str],
    ) -> list[str]:
        errs: list[str] = []
        normalized = contact_hygiene_service.normalize_phone_e164(phone_e164)
        if not normalized:
            errs.append("invalid_phone")
            return errs
        if normalized in seen_phones:
            errs.append("duplicate_phone")
        else:
            seen_phones.add(normalized)
        if country_code and len(country_code.strip()) != 2:
            errs.append("invalid_country")
        if (opt_in_status or "").lower() != "opted_in":
            errs.append("missing_consent")
        if (opt_in_status or "").lower() in {"opted_out", "unsubscribed"} or unsubscribed_at is not None:
            errs.append("opted_out_contact")
        if blocked_at is not None:
            errs.append("blocked_contact")
        for var in required_vars:
            if variables.get(var) in (None, ""):
                errs.append(f"missing_required_template_variable:{var}")
        return errs

    async def finalize_and_freeze(self, *, business_id: UUID, campaign_id: UUID) -> dict:
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
            raise NotFoundException("Campaign not found")
        if campaign.status != "draft":
            raise BadRequestException("Campaign must be in DRAFT to finalize recipients")
        if not campaign.template_id:
            raise BadRequestException("Campaign template is required")

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
            raise BadRequestException("Campaign template not found")
        required_vars = self._required_template_variables(template)
        suppression_engine = ContactSuppressionEngine(self.db)

        await self.state.transition_campaign(
            business_id=business_id,
            campaign_id=campaign_id,
            new_status="validating",
            reason="finalize_recipients",
        )

        now = datetime.now(timezone.utc)
        seen_phones: set[str] = set()
        total = 0
        eligible = 0
        skipped = 0
        errors: list[dict] = []

        # clear previous frozen recipients before freeze refresh
        rows = await self.db.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.business_id == business_id,
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.deleted_at.is_(None),
            )
        )
        for row in rows.scalars().all():
            row.deleted_at = now

        if campaign.segment_id:
            segment = (
                await self.db.execute(
                    select(ConversationSavedView).where(
                        ConversationSavedView.id == campaign.segment_id,
                        ConversationSavedView.business_id == business_id,
                        ConversationSavedView.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if not segment:
                raise BadRequestException("Segment not found")
            filters = ((segment.filters_json or {}).get("filters") or {})
            segment_service = ContactSegmentService(self.db)
            stmt = select(Contact).where(Contact.business_id == business_id, Contact.deleted_at.is_(None))
            stmt = segment_service._apply_filters(stmt, filters)  # tenant-scoped and controlled input
            contacts = (await self.db.execute(stmt)).scalars().all()
            for c in contacts:
                total += 1
                variables = dict(c.custom_attributes or {})
                decision = await suppression_engine.evaluate_for_campaign_recipient(
                    campaign=campaign,
                    phone_e164=c.normalized_phone,
                    contact=c,
                    variables=variables,
                    required_vars=required_vars,
                    country_code=c.country_code,
                    seen_phones=seen_phones,
                )
                errs = decision.reasons
                status = "pending" if decision.allowed else "skipped"
                eligibility_status = "eligible" if decision.allowed else "ineligible"
                if not decision.allowed:
                    skipped += 1
                    errors.append({"source": "segment", "contact_id": str(c.id), "errors": errs})
                else:
                    eligible += 1
                rec = CampaignRecipient(
                    campaign_id=campaign_id,
                    business_id=business_id,
                    contact_id=c.id,
                    phone_e164=c.normalized_phone or "",
                    wa_id=c.wa_id,
                    name=c.display_name,
                    status=status,
                    eligibility_status=eligibility_status,
                    eligibility_reason=",".join(errs) if errs else None,
                    variables_json=variables,
                    rendered_template_json={},
                    skipped_at=now if errs else None,
                )
                self.db.add(rec)
                await self.db.flush()
                if errs:
                    self.db.add(
                        CampaignRecipientEvent(
                            campaign_id=campaign_id,
                            campaign_recipient_id=rec.id,
                            business_id=business_id,
                            event_type="campaign_recipient.suppression_applied",
                            old_status="pending",
                            new_status="skipped",
                            payload_json={"suppression_reasons": errs},
                            error_code=errs[0],
                            error_message="suppressed_by_policy",
                        )
                    )
        elif campaign.csv_import_id:
            csv_job = (
                await self.db.execute(
                    select(ContactImportJob).where(
                        ContactImportJob.id == campaign.csv_import_id,
                        ContactImportJob.business_id == business_id,
                        ContactImportJob.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if not csv_job:
                raise BadRequestException("CSV import not found")
            csv_rows = (
                await self.db.execute(
                    select(ContactImportRow).where(
                        ContactImportRow.import_job_id == csv_job.id,
                        ContactImportRow.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            for row in csv_rows:
                payload = row.payload_json or {}
                total += 1
                raw_phone = payload.get("phone_e164")
                normalized = contact_hygiene_service.normalize_phone_e164(raw_phone)
                variables = {k: v for k, v in payload.items() if k not in {"phone_e164", "wa_id", "name", "country_code"}}
                decision = await suppression_engine.evaluate_for_campaign_recipient(
                    campaign=campaign,
                    phone_e164=normalized,
                    contact=None,
                    variables=variables,
                    required_vars=required_vars,
                    country_code=payload.get("country_code"),
                    seen_phones=seen_phones,
                )
                errs = decision.reasons
                status = "pending" if decision.allowed else "skipped"
                eligibility_status = "eligible" if decision.allowed else "ineligible"
                if not decision.allowed:
                    skipped += 1
                    errors.append({"source": "csv", "row_number": row.row_number, "errors": errs})
                else:
                    eligible += 1
                rec = CampaignRecipient(
                    campaign_id=campaign_id,
                    business_id=business_id,
                    contact_id=None,
                    phone_e164=normalized or "",
                    wa_id=payload.get("wa_id"),
                    name=payload.get("name"),
                    status=status,
                    eligibility_status=eligibility_status,
                    eligibility_reason=",".join(errs) if errs else None,
                    variables_json=variables,
                    rendered_template_json={},
                    skipped_at=now if errs else None,
                )
                self.db.add(rec)
                await self.db.flush()
                if errs:
                    self.db.add(
                        CampaignRecipientEvent(
                            campaign_id=campaign_id,
                            campaign_recipient_id=rec.id,
                            business_id=business_id,
                            event_type="campaign_recipient.suppression_applied",
                            old_status="pending",
                            new_status="skipped",
                            payload_json={"suppression_reasons": errs},
                            error_code=errs[0],
                            error_message="suppressed_by_policy",
                        )
                    )
        else:
            raise BadRequestException("Campaign must have saved segment or CSV source")

        campaign.total_recipients = total
        campaign.eligible_recipients = eligible
        campaign.skipped_recipients = skipped
        CampaignService.invalidate_preview(campaign)
        await self.state.transition_campaign(
            business_id=business_id,
            campaign_id=campaign_id,
            new_status="ready",
            reason="recipient_freeze_completed",
        )
        await CampaignBlackBoxRecorder(self.db).record(
            business_id=business_id,
            campaign_id=campaign_id,
            event_type="recipients_frozen",
            message=f"{eligible:,} eligible recipients frozen ({total:,} total, {skipped:,} skipped)",
            payload_json={
                "total_recipients": total,
                "eligible_recipients": eligible,
                "skipped_recipients": skipped,
            },
        )
        await self.db.flush()
        return {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "total_recipients": total,
            "eligible_recipients": eligible,
            "skipped_recipients": skipped,
            "validation_errors": errors,
        }

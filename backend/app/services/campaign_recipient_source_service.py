from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.business_domains import (
    Campaign,
    CampaignRecipient,
    CampaignRecipientSnapshot,
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
    FREEZE_FLUSH_BATCH_SIZE = 250

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

    def _build_freeze_summary(self, *, freeze_version: int, freeze_batch_id: str, total: int, eligible: int, skipped: int, errors: list[dict]) -> dict:
        reason_counts: dict[str, int] = {}
        for err in errors:
            for reason in err.get("errors") or []:
                key = str(reason)
                reason_counts[key] = int(reason_counts.get(key, 0)) + 1
        top_reasons = sorted(reason_counts.items(), key=lambda x: (-x[1], x[0]))[:20]
        return {
            "freeze_version": freeze_version,
            "freeze_batch_id": freeze_batch_id,
            "total_recipients": total,
            "eligible_recipients": eligible,
            "skipped_recipients": skipped,
            "validation_error_count": len(errors),
            "top_validation_reasons": [{"reason": k, "count": v} for k, v in top_reasons],
        }

    def _summary_hash(self, value: dict) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def finalize_and_freeze(self, *, business_id: UUID, campaign_id: UUID) -> dict:
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
        if campaign.status not in {"draft", "validating"}:
            raise BadRequestException("Campaign must be in DRAFT to finalize recipients")
        if not campaign.template_id:
            raise BadRequestException("Campaign template is required")
        mapping = dict(campaign.variable_mapping_json or {})
        finalize_lock = dict(mapping.get("__recipient_finalize_lock") or {})
        if bool(finalize_lock.get("in_progress")):
            raise BadRequestException("Recipient finalize already in progress for this campaign")
        freeze_version = int(mapping.get("__recipient_freeze_version") or 0) + 1
        freeze_batch_id = uuid.uuid4().hex
        lock_token = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        mapping["__recipient_finalize_lock"] = {
            "in_progress": True,
            "started_at": now.isoformat(),
            "token": lock_token,
        }
        campaign.variable_mapping_json = mapping
        await self.db.flush()

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

        if campaign.status == "draft":
            await self.state.transition_campaign(
                business_id=business_id,
                campaign_id=campaign_id,
                new_status="validating",
                reason="finalize_recipients",
            )

        seen_phones: set[str] = set()
        total = 0
        eligible = 0
        skipped = 0
        errors: list[dict] = []

        # clear previous active freeze recipients before creating the next freeze version
        rows = await self.db.stream(
            select(CampaignRecipient).where(
                CampaignRecipient.business_id == business_id,
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.deleted_at.is_(None),
            ).execution_options(yield_per=self.FREEZE_FLUSH_BATCH_SIZE)
        )
        async for row in rows.scalars():
            row.deleted_at = now

        async def persist_recipient_batch(buffer: list[tuple[CampaignRecipient, list[str]]]) -> None:
            if not buffer:
                return
            await self.db.flush()
            for rec, errs in buffer:
                if not errs:
                    continue
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
            await self.db.flush()
            buffer.clear()

        recipient_buffer: list[tuple[CampaignRecipient, list[str]]] = []

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
            stream = await self.db.stream(stmt.execution_options(yield_per=self.FREEZE_FLUSH_BATCH_SIZE))
            async for c in stream.scalars():
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
                    rendered_template_json={
                        "__freeze_batch_id": freeze_batch_id,
                        "__freeze_version": freeze_version,
                    },
                    skipped_at=now if errs else None,
                )
                self.db.add(rec)
                recipient_buffer.append((rec, errs))
                if len(recipient_buffer) >= self.FREEZE_FLUSH_BATCH_SIZE:
                    await persist_recipient_batch(recipient_buffer)
            await persist_recipient_batch(recipient_buffer)
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
            stream = await self.db.stream(
                select(ContactImportRow).where(
                    ContactImportRow.import_job_id == csv_job.id,
                    ContactImportRow.deleted_at.is_(None),
                ).execution_options(yield_per=self.FREEZE_FLUSH_BATCH_SIZE)
            )
            async for row in stream.scalars():
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
                    rendered_template_json={
                        "__freeze_batch_id": freeze_batch_id,
                        "__freeze_version": freeze_version,
                    },
                    skipped_at=now if errs else None,
                )
                self.db.add(rec)
                recipient_buffer.append((rec, errs))
                if len(recipient_buffer) >= self.FREEZE_FLUSH_BATCH_SIZE:
                    await persist_recipient_batch(recipient_buffer)
            await persist_recipient_batch(recipient_buffer)
        else:
            raise BadRequestException("Campaign must have saved segment or CSV source")

        summary = self._build_freeze_summary(
            freeze_version=freeze_version,
            freeze_batch_id=freeze_batch_id,
            total=total,
            eligible=eligible,
            skipped=skipped,
            errors=errors,
        )
        snapshot = CampaignRecipientSnapshot(
            campaign_id=campaign_id,
            recipient_set_hash=self._summary_hash(summary),
            recipients=summary,
        )
        self.db.add(snapshot)
        await self.db.flush()

        campaign.total_recipients = total
        campaign.eligible_recipients = eligible
        campaign.skipped_recipients = skipped
        mapping = dict(campaign.variable_mapping_json or {})
        mapping["__recipient_freeze_version"] = freeze_version
        mapping["__active_recipient_freeze_batch_id"] = freeze_batch_id
        mapping["__active_recipient_freeze_snapshot_id"] = str(snapshot.id)
        mapping["__recipient_finalize_lock"] = {
            "in_progress": False,
            "released_at": datetime.now(timezone.utc).isoformat(),
            "token": lock_token,
        }
        campaign.variable_mapping_json = mapping
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
            payload_json=summary,
        )
        await self.db.flush()
        return {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "total_recipients": total,
            "eligible_recipients": eligible,
            "skipped_recipients": skipped,
            "validation_errors": errors,
            "freeze_version": freeze_version,
            "freeze_batch_id": freeze_batch_id,
            "validation_summary_snapshot": summary,
        }

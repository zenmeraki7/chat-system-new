from uuid import UUID

import csv
import io
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.models.business_domains import Campaign, CampaignExecutionEvent, CampaignRecipient, CampaignRecipientEvent, CampaignSendJob, CampaignStatusEvent, JobOperation, MessageOutbox, OutboxEvent, WhatsAppMessageTemplate, WebhookEvent, BusinessDashboardStat, CampaignApprovalSnapshot, Contact
from app.models.business import Business
from app.models.business_domains import WhatsAppPhoneNumber, WhatsAppBusinessAccount, WhatsAppIntegration
from app.schemas.campaign import (
    CampaignCreateRequest,
    CampaignCreateResponse,
    CampaignPreviewResponse,
    CampaignFinalizeResponse,
    CampaignRecipientSourceRequest,
    CampaignTemplateVariableMappingRequest,
    CampaignTemplateVariableValidationResponse,
    CampaignTransitionRequest,
    CampaignTransitionResponse,
    CampaignRecipientTransitionRequest,
    CampaignRecipientTransitionResponse,
)
from app.services.campaign_recipient_source_service import CampaignRecipientSourceService
from app.services.campaign_pause_service import CampaignPauseService
from app.services.campaign_cancel_service import CampaignCancelService
from app.services.campaign_service import CampaignService
from app.services.campaign_state_service import CampaignStateService
from app.services.campaign_resume_service import CampaignResumeService
from app.services.campaign_blackbox_recorder import CampaignBlackBoxRecorder
from app.services.campaign_recipient_explainability_service import CampaignRecipientExplainabilityService
from app.services.audience_warmth_service import AudienceWarmthService
from app.services.campaign_health_service import CampaignHealthService
from app.services.csv_safety import escape_csv_cell
from app.services.object_storage_service import object_storage_service
from app.services.table_registry import validate_table_query
from app.services.query_cost_service import classify_table_query
from app.services.data_freshness_service import freshness_live_db
from app.utils.cursor import decode_cursor, encode_cursor, InvalidCursorError, stable_hash


router = APIRouter(prefix="/campaigns", tags=["Campaigns"])
LAUNCH_FRESHNESS_MAX_LAG_SECONDS = 900


def _campaign_recipient_query_fingerprint(*, business_id: UUID, campaign_id: UUID, status: str | None, search: str | None, sort_by: str, sort_dir: str) -> str:
    return stable_hash(
        {
            "resource": "campaign_recipients",
            "businessId": str(business_id),
            "campaignId": str(campaign_id),
            "status": status or "",
            "search": (search or "").strip().lower(),
            "sort": {"key": sort_by, "dir": sort_dir},
        }
    )


def _compute_campaign_recipient_snapshot_hash(rows: list[CampaignRecipient]) -> str:
    import hashlib
    parts: list[str] = []
    for r in rows:
        parts.append(
            "|".join(
                [
                    str(r.id),
                    str(r.status or ""),
                    str(r.eligibility_status or ""),
                    str(r.eligibility_reason or ""),
                    str(r.phone_e164 or ""),
                ]
            )
        )
    parts.sort()
    blob = "\n".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _campaign_execution_mode(campaign: Campaign) -> str:
    mapping = campaign.variable_mapping_json or {}
    mode = str(mapping.get("__execution_mode__") or "").strip().upper()
    if mode in {"STANDARD", "SLOW_START", "AGGRESSIVE", "SAFE_MODE"}:
        return mode
    return "STANDARD"


def _execution_mode(campaign: Campaign) -> str:
    return "DRY_RUN" if str(campaign.environment or "").lower() == "dry_run" else "LIVE"


@router.post("", response_model=CampaignCreateResponse)
async def create_campaign(
    payload: CampaignCreateRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    service = CampaignService(db)
    row = await service.create_draft_campaign(
        business_id=actor.business.id,
        created_by_user_id=actor.user.id,
        name=payload.name.strip(),
        phone_number_id=payload.phone_number_id.strip(),
        template_id=payload.template_id,
        segment_id=payload.segment_id,
        csv_import_id=payload.csv_import_id,
        scheduled_at=payload.scheduled_at,
        campaign_type=payload.type,
    )
    await db.commit()
    return CampaignCreateResponse(
        campaign_id=row.id,
        status=row.status,
        name=row.name,
        phone_number_id=row.phone_number_id,
        template_id=row.template_id,
        template_name=row.template_name,
        template_language=row.template_language,
        template_category=row.template_category,
        segment_id=row.segment_id,
        csv_import_id=row.csv_import_id,
        scheduled_at=row.scheduled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=dict)
async def list_campaigns(
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    search: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(default=100, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Campaign).where(
        Campaign.business_id == actor.business.id,
        Campaign.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(Campaign.status == status.lower())
    if type:
        stmt = stmt.where(Campaign.type == type.lower())
    if owner:
        stmt = stmt.where(Campaign.created_by_user_id == UUID(owner))
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(or_(Campaign.name.ilike(q), Campaign.template_name.ilike(q), Campaign.phone_number_id.ilike(q)))
    sort_map = {
        "created_at": Campaign.created_at,
        "updated_at": Campaign.updated_at,
        "name": Campaign.name,
        "status": Campaign.status,
        "eligible_recipients": Campaign.eligible_recipients,
        "delivered_count": Campaign.delivered_count,
        "actual_cost": Campaign.actual_cost,
    }
    sort_key = sort_map.get(sort_by, Campaign.created_at)
    sort_desc = str(sort_dir).lower() != "asc"
    if cursor:
        cursor_row = (
            await db.execute(
                select(Campaign.id, sort_key).where(
                    Campaign.id == UUID(cursor),
                    Campaign.business_id == actor.business.id,
                    Campaign.deleted_at.is_(None),
                )
            )
        ).first()
        if cursor_row is not None:
            cursor_id, cursor_val = cursor_row
            if cursor_val is not None:
                if sort_desc:
                    stmt = stmt.where(or_(sort_key < cursor_val, and_(sort_key == cursor_val, Campaign.id < cursor_id)))
                else:
                    stmt = stmt.where(or_(sort_key > cursor_val, and_(sort_key == cursor_val, Campaign.id > cursor_id)))
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    order_primary = sort_key.desc() if sort_desc else sort_key.asc()
    order_secondary = Campaign.id.desc() if sort_desc else Campaign.id.asc()
    rows = (await db.execute(stmt.order_by(order_primary, order_secondary).limit(limit + 1))).scalars().all()
    page_rows = rows[:limit]
    next_cursor = str(page_rows[-1].id) if len(rows) > limit and page_rows else None
    items = [
        {
            "campaign_id": str(r.id),
            "name": r.name,
            "status": r.status,
            "type": r.type,
            "campaign_execution_mode": _campaign_execution_mode(r),
            "execution_mode": _execution_mode(r),
            "created_by_user_id": str(r.created_by_user_id) if r.created_by_user_id else None,
            "phone_number_id": r.phone_number_id,
            "template_id": str(r.template_id) if r.template_id else None,
            "template_name": r.template_name,
            "template_category": r.template_category,
            "total_recipients": int(r.total_recipients or 0),
            "eligible_recipients": int(r.eligible_recipients or 0),
            "delivered_count": int(r.delivered_count or 0),
            "read_count": int(r.read_count or 0),
            "replied_count": int(r.replied_count or 0),
            "failed_count": int(r.failed_count or 0),
            "actual_cost": r.actual_cost,
            "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in page_rows
    ]
    return {"items": items, "next_cursor": next_cursor, "total": total, "freshness": freshness_live_db()}


@router.post("/{campaign_id}/recipient-source", response_model=dict)
async def set_campaign_recipient_source(
    campaign_id: str,
    payload: CampaignRecipientSourceRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    service = CampaignRecipientSourceService(db)
    row = await service.set_source(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        source_type=payload.source_type,
        segment_id=payload.segment_id,
        csv_import_id=payload.csv_import_id,
    )
    await db.commit()
    return {
        "campaign_id": str(row.id),
        "source_type": payload.source_type,
        "segment_id": str(row.segment_id) if row.segment_id else None,
        "csv_import_id": str(row.csv_import_id) if row.csv_import_id else None,
        "status": row.status,
    }


@router.post("/{campaign_id}/finalize-recipients", response_model=CampaignFinalizeResponse)
async def finalize_campaign_recipients(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    service = CampaignRecipientSourceService(db)
    summary = await service.finalize_and_freeze(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    await db.commit()
    return CampaignFinalizeResponse(**summary)


@router.post("/{campaign_id}/template-variable-mapping", response_model=dict)
async def set_campaign_template_variable_mapping(
    campaign_id: str,
    payload: CampaignTemplateVariableMappingRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    service = CampaignService(db)
    row = await service.set_variable_mapping(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        variable_mapping=payload.variable_mapping,
    )
    await db.commit()
    return {
        "campaign_id": str(row.id),
        "variable_mapping_json": row.variable_mapping_json,
        "status": row.status,
    }


@router.get("/{campaign_id}/template-variable-validation", response_model=CampaignTemplateVariableValidationResponse)
async def validate_campaign_template_variables(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    service = CampaignService(db)
    errors = await service.validate_template_mapping_for_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    return CampaignTemplateVariableValidationResponse(
        campaign_id=UUID(campaign_id),
        valid=len(errors) == 0,
        errors=errors,
    )


@router.post("/{campaign_id}/preview", response_model=CampaignPreviewResponse)
async def preview_campaign(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    preview = await CampaignService(db).preview_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    await db.commit()
    return CampaignPreviewResponse(**preview)


@router.get("/{campaign_id}", response_model=dict)
async def get_campaign_state(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    svc = CampaignStateService(db)
    campaign, allowed_next = await svc.get_campaign_with_allowed_next(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    return {
        "campaign_id": str(campaign.id),
        "status": campaign.status,
        "campaign_execution_mode": _campaign_execution_mode(campaign),
        "execution_mode": _execution_mode(campaign),
        "allowed_next_statuses": allowed_next,
        "updated_at": campaign.updated_at.isoformat(),
    }


@router.post("/{campaign_id}/transition", response_model=CampaignTransitionResponse)
async def transition_campaign(
    campaign_id: str,
    payload: CampaignTransitionRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    target = (payload.to_status or "").lower()
    if target in {"scheduled", "queued", "running"}:
        validation_errors = await CampaignService(db).validate_template_mapping_for_campaign(
            business_id=actor.business.id,
            campaign_id=UUID(campaign_id),
        )
        if validation_errors:
            from app.core.exceptions import BadRequestException
            raise BadRequestException(
                "Campaign template variable validation failed; resolve errors before launch transitions"
            )
    svc = CampaignStateService(db)
    campaign = await svc.transition_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        new_status=target,
        reason=payload.reason,
    )
    await db.commit()
    return CampaignTransitionResponse(
        campaign_id=campaign.id,
        status=campaign.status,
        updated_at=campaign.updated_at,
    )


@router.patch("/{campaign_id}", response_model=dict)
async def update_campaign(
    campaign_id: str,
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("Campaign not found")
    if "name" in payload and payload["name"]:
        row.name = str(payload["name"]).strip()
        CampaignService.invalidate_preview(row)
    if "scheduled_at" in payload:
        row.scheduled_at = payload["scheduled_at"]
    if "type" in payload and payload["type"]:
        row.type = str(payload["type"]).strip().lower()
        CampaignService.invalidate_preview(row)
    if "template_id" in payload and payload["template_id"]:
        template_row = (
            await db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == UUID(str(payload["template_id"])),
                    WhatsAppMessageTemplate.business_id == actor.business.id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not template_row:
            raise BadRequestException("template_id is invalid for this business")
        row.template_id = template_row.id
        row.template_name = template_row.name
        row.template_language = template_row.language
        row.template_category = template_row.category
        CampaignService.invalidate_preview(row)
    if "segment_id" in payload:
        row.segment_id = UUID(str(payload["segment_id"])) if payload["segment_id"] else None
        CampaignService.invalidate_preview(row)
    if "csv_import_id" in payload:
        row.csv_import_id = UUID(str(payload["csv_import_id"])) if payload["csv_import_id"] else None
        CampaignService.invalidate_preview(row)
    await db.commit()
    return {"campaign_id": str(row.id), "status": row.status, "updated_at": row.updated_at.isoformat()}


@router.delete("/{campaign_id}", response_model=dict)
async def delete_campaign(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("Campaign not found")
    row.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"campaign_id": str(row.id), "deleted": True}


@router.post("/{campaign_id}/schedule", response_model=CampaignTransitionResponse)
async def schedule_campaign(
    campaign_id: str,
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")
    if not payload.get("scheduled_at"):
        raise BadRequestException("scheduled_at is required")
    campaign.scheduled_at = payload["scheduled_at"]
    await CampaignStateService(db).transition_campaign(
        business_id=actor.business.id,
        campaign_id=campaign.id,
        new_status="scheduled",
        reason="manual_schedule",
    )
    await db.commit()
    return CampaignTransitionResponse(campaign_id=campaign.id, status=campaign.status, updated_at=campaign.updated_at)


@router.post("/{campaign_id}/launch", response_model=CampaignTransitionResponse)
async def launch_campaign(
    campaign_id: str,
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    if not bool(payload.get("confirm")):
        raise BadRequestException("Explicit launch confirmation is required")
    confirmation_text = str(payload.get("confirmation_text") or "").strip().upper()
    if confirmation_text != "CONFIRM":
        raise BadRequestException("confirmation_text must be CONFIRM")
    expected_hash = str(payload.get("expected_confirmation_hash") or "").strip()
    if not expected_hash:
        raise BadRequestException("expected_confirmation_hash is required")
    launch_snapshot_id = str(payload.get("launch_snapshot_id") or "").strip()
    if not launch_snapshot_id:
        raise BadRequestException("launch_snapshot_id is required")
    execution_mode = str(payload.get("execution_mode") or "LIVE").strip().upper()
    if execution_mode not in {"LIVE", "DRY_RUN"}:
        raise BadRequestException("execution_mode must be LIVE or DRY_RUN")
    campaign_execution_mode = str(payload.get("campaign_execution_mode") or "").strip().upper()
    if campaign_execution_mode and campaign_execution_mode not in {"STANDARD", "SLOW_START", "AGGRESSIVE", "SAFE_MODE"}:
        raise BadRequestException("campaign_execution_mode must be STANDARD, SLOW_START, AGGRESSIVE, or SAFE_MODE")

    campaign_row = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign_row:
        raise NotFoundException("Campaign not found")
    launch_snapshot = (
        await db.execute(
            select(CampaignApprovalSnapshot).where(
                CampaignApprovalSnapshot.id == UUID(launch_snapshot_id),
                CampaignApprovalSnapshot.business_id == actor.business.id,
                CampaignApprovalSnapshot.campaign_id == campaign_row.id,
                CampaignApprovalSnapshot.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if launch_snapshot is None:
        raise BadRequestException("Launch snapshot not found; regenerate launch confirmation")
    frozen = dict(launch_snapshot.template_snapshot_json or {})
    frozen_hash = str(frozen.get("confirmation_hash") or "").strip()
    if not frozen_hash:
        raise BadRequestException("Launch snapshot invalid; regenerate launch confirmation")
    if expected_hash != frozen_hash:
        raise BadRequestException("Launch confirmation is stale; refresh confirmation and try again")

    # Anti-footgun launch checks
    now = datetime.now(timezone.utc)
    business = (
        await db.execute(select(Business).where(Business.id == actor.business.id, Business.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if not business or (business.status or "").lower() == "suspended":
        raise BadRequestException("Business suspended; campaign launch blocked")
    if business and (business.billing_status or "").lower() in {"payment_failed", "suspended"}:
        raise BadRequestException("Wallet balance insufficient / billing blocked")

    template_errors = await CampaignService(db).validate_template_mapping_for_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    if template_errors:
        raise BadRequestException("Template or variable mapping is invalid; re-preview after fixing errors")
    if int(launch_snapshot.recipient_count or 0) <= 0:
        raise BadRequestException("Recipient count is zero; launch blocked")
    dashboard = (
        await db.execute(
            select(BusinessDashboardStat).where(
                BusinessDashboardStat.business_id == actor.business.id,
                BusinessDashboardStat.deleted_at.is_(None),
            ).order_by(BusinessDashboardStat.date_bucket.desc(), BusinessDashboardStat.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if dashboard is not None and dashboard.date_bucket is not None:
        lag = int((now - dashboard.date_bucket).total_seconds())
        if lag > LAUNCH_FRESHNESS_MAX_LAG_SECONDS:
            raise BadRequestException("Contacts snapshot stale; refresh audience data before launch")

    phone = (
        await db.execute(
            select(WhatsAppPhoneNumber).where(
                WhatsAppPhoneNumber.business_id == actor.business.id,
                WhatsAppPhoneNumber.phone_number_id == campaign_row.phone_number_id,
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not phone or phone.disconnected_at is not None or phone.disabled_at is not None or (phone.status or "").lower() != "active":
        raise BadRequestException("Phone number disconnected/unhealthy; launch blocked")
    if (phone.quality_rating or "").lower() in {"red", "low"}:
        raise BadRequestException("Quality rating unsafe; launch blocked")
    if phone.last_health_check_at is not None:
        lag = int((now - phone.last_health_check_at).total_seconds())
        if lag > LAUNCH_FRESHNESS_MAX_LAG_SECONDS:
            raise BadRequestException("Phone health stale; refresh phone health before launch")
    if phone.last_template_sync_at is not None:
        lag = int((now - phone.last_template_sync_at).total_seconds())
        if lag > LAUNCH_FRESHNESS_MAX_LAG_SECONDS:
            raise BadRequestException("Template status stale; sync templates before launch")

    if campaign_row.waba_id:
        waba = (
            await db.execute(
                select(WhatsAppBusinessAccount).where(
                    WhatsAppBusinessAccount.business_id == actor.business.id,
                    WhatsAppBusinessAccount.waba_id == campaign_row.waba_id,
                    WhatsAppBusinessAccount.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not waba:
            raise BadRequestException("WABA disconnected; launch blocked")
        if waba.last_webhook_received_at is not None:
            lag = int((now - waba.last_webhook_received_at).total_seconds())
            if lag > LAUNCH_FRESHNESS_MAX_LAG_SECONDS:
                raise BadRequestException("Webhook lag too high; inbound processing stale before launch")
    integ = (
        await db.execute(
            select(WhatsAppIntegration).where(
                WhatsAppIntegration.business_id == actor.business.id,
                WhatsAppIntegration.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if integ and (integ.status or "").lower() not in {"connected"}:
        raise BadRequestException("WABA disconnected; launch blocked")
    if integ and integ.updated_at is not None:
        lag = int((now - integ.updated_at).total_seconds())
        if lag > (LAUNCH_FRESHNESS_MAX_LAG_SECONDS * 2):
            raise BadRequestException("Wallet or integration status stale; refresh account health before launch")

    if campaign_row.csv_import_id:
        bad_import_rows = (
            await db.execute(
                select(CampaignRecipient.id).where(
                    CampaignRecipient.campaign_id == campaign_row.id,
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.contact_id.is_(None),
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.eligibility_reason.ilike("%missing_consent%"),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if bad_import_rows is not None:
            raise BadRequestException("Imported contacts with missing opt-in source/consent found; launch blocked")

    current_rows = (
        await db.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign_row.id,
                CampaignRecipient.business_id == actor.business.id,
                CampaignRecipient.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    current_hash = _compute_campaign_recipient_snapshot_hash(current_rows)
    if current_hash != str(frozen.get("recipient_snapshot_hash") or ""):
        raise BadRequestException("Recipient set changed after snapshot; regenerate launch snapshot")
    if str(frozen.get("template_id") or "") != str(campaign_row.template_id or ""):
        raise BadRequestException("Template changed after snapshot; regenerate launch snapshot")
    if str(frozen.get("phone_number_id") or "") != str(campaign_row.phone_number_id or ""):
        raise BadRequestException("Phone number changed after snapshot; regenerate launch snapshot")
    if not campaign_execution_mode:
        campaign_execution_mode = "STANDARD"
        if (campaign_row.template_category or "").lower() == "marketing":
            is_new_business = False
            if business and business.created_at is not None:
                is_new_business = business.created_at >= (datetime.now(timezone.utc) - timedelta(days=30))
            warmth = await AudienceWarmthService(db).score_campaign_audience(
                business_id=actor.business.id,
                campaign_id=campaign_row.id,
            )
            q = warmth.get("audience_quality") or {}
            cold = int(q.get("cold") or 0)
            total = int(q.get("total") or 0)
            cold_ratio = (float(cold) / float(total)) if total > 0 else 0.0
            if is_new_business or campaign_row.csv_import_id is not None or cold_ratio >= 0.20:
                campaign_execution_mode = "SAFE_MODE"
    mapping = dict(campaign_row.variable_mapping_json or {})
    mapping["__execution_mode__"] = campaign_execution_mode
    campaign_row.variable_mapping_json = mapping
    campaign_row.environment = "dry_run" if execution_mode == "DRY_RUN" else "live"
    campaign_row.campaign_config_hash = CampaignService.compute_campaign_config_hash(campaign_row)
    if not campaign_row.preview_hash:
        raise BadRequestException("Preview invalidated or missing; regenerate preview before launch")
    if campaign_row.preview_hash != campaign_row.campaign_config_hash:
        raise BadRequestException("Campaign changed after preview; re-preview is required before launch")

    campaign = await CampaignStateService(db).transition_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        new_status="queued",
        reason="manual_launch",
    )
    await CampaignBlackBoxRecorder(db).record(
        business_id=actor.business.id,
        campaign_id=campaign.id,
        event_type="campaign_launched",
        message="Campaign launched and queued for dispatch",
        payload_json={
            "execution_mode": execution_mode,
            "campaign_execution_mode": campaign_execution_mode,
            "eligible_recipients": int(launch_snapshot.recipient_count or 0),
            "skipped_recipients": int((frozen.get("preview") or {}).get("skipped_recipients") or 0),
            "estimated_cost": (frozen.get("preview") or {}).get("estimated_cost") or {"amount": 0, "currency": "USD"},
            "estimated_duration_minutes": int((frozen.get("preview") or {}).get("estimated_duration_minutes") or 0),
            "launch_snapshot_id": str(launch_snapshot.id),
        },
    )
    await db.commit()
    return CampaignTransitionResponse(campaign_id=campaign.id, status=campaign.status, updated_at=campaign.updated_at)


@router.get("/{campaign_id}/launch-confirmation", response_model=dict)
async def get_launch_confirmation(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")

    preview = await CampaignService(db).preview_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    recipients = (
        await db.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.business_id == actor.business.id,
                CampaignRecipient.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    recipient_snapshot_hash = _compute_campaign_recipient_snapshot_hash(recipients)
    phone = (
        await db.execute(
            select(WhatsAppPhoneNumber).where(
                WhatsAppPhoneNumber.business_id == actor.business.id,
                WhatsAppPhoneNumber.phone_number_id == campaign.phone_number_id,
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    waba = None
    if campaign.waba_id:
        waba = (
            await db.execute(
                select(WhatsAppBusinessAccount).where(
                    WhatsAppBusinessAccount.business_id == actor.business.id,
                    WhatsAppBusinessAccount.waba_id == campaign.waba_id,
                    WhatsAppBusinessAccount.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    integ = (
        await db.execute(
            select(WhatsAppIntegration).where(
                WhatsAppIntegration.business_id == actor.business.id,
                WhatsAppIntegration.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    import hashlib
    confirmation_material = "|".join(
        [
            str(campaign.id),
            str(campaign.template_name or ""),
            str(campaign.phone_number_id or ""),
            str(preview.get("eligible_recipients") or 0),
            str(preview.get("skipped_recipients") or 0),
            str((preview.get("estimated_cost") or {}).get("amount") or 0),
            str((preview.get("estimated_cost") or {}).get("currency") or ""),
            str(preview.get("estimated_duration_minutes") or 0),
        ]
    )
    confirmation_hash = hashlib.sha256(confirmation_material.encode("utf-8")).hexdigest()
    frozen_payload = {
        "campaign_id": str(campaign.id),
        "template_id": str(campaign.template_id) if campaign.template_id else None,
        "template_name": campaign.template_name,
        "phone_number_id": campaign.phone_number_id,
        "waba_id": campaign.waba_id,
        "preview": preview,
        "recipient_snapshot_hash": recipient_snapshot_hash,
        "phone_health": {
            "status": (phone.status if phone else None),
            "quality_rating": (phone.quality_rating if phone else None),
            "last_health_check_at": (phone.last_health_check_at.isoformat() if phone and phone.last_health_check_at else None),
        },
        "webhook_health": {
            "last_webhook_received_at": (waba.last_webhook_received_at.isoformat() if waba and waba.last_webhook_received_at else None),
        },
        "token_integration_status": {
            "integration_status": (integ.status if integ else None),
            "integration_updated_at": (integ.updated_at.isoformat() if integ and integ.updated_at else None),
        },
        "confirmation_hash": confirmation_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    snapshot = (
        await db.execute(
            select(CampaignApprovalSnapshot).where(
                CampaignApprovalSnapshot.business_id == actor.business.id,
                CampaignApprovalSnapshot.campaign_id == campaign.id,
                CampaignApprovalSnapshot.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        snapshot = CampaignApprovalSnapshot(
            business_id=actor.business.id,
            campaign_id=campaign.id,
            approved_by_user_id=actor.user.id,
            template_snapshot_json=frozen_payload,
            recipient_count=int(preview.get("eligible_recipients") or 0),
            estimated_cost=float((preview.get("estimated_cost") or {}).get("amount") or 0.0),
            compliance_acknowledged=False,
        )
        db.add(snapshot)
    else:
        snapshot.template_snapshot_json = frozen_payload
        snapshot.recipient_count = int(preview.get("eligible_recipients") or 0)
        snapshot.estimated_cost = float((preview.get("estimated_cost") or {}).get("amount") or 0.0)
        snapshot.approved_by_user_id = actor.user.id
    await db.commit()
    await db.refresh(snapshot)
    return {
        "campaign_id": str(campaign.id),
        "strict_confirmation_required": True,
        "campaign_execution_mode": _campaign_execution_mode(campaign),
        "execution_mode": _execution_mode(campaign),
        "campaign_type": campaign.type,
        "template_category": campaign.template_category,
        "template_name": campaign.template_name,
        "phone_number_id": campaign.phone_number_id,
        "recipients": int(preview.get("eligible_recipients") or 0),
        "skipped": int(preview.get("skipped_recipients") or 0),
        "estimated_cost": preview.get("estimated_cost") or {"amount": 0, "currency": "USD"},
        "estimated_duration_minutes": int(preview.get("estimated_duration_minutes") or 0),
        "exclusions_notice": "This campaign will exclude opted-out, blocked, invalid, and duplicate contacts.",
        "confirmation_hash": confirmation_hash,
        "launch_snapshot_id": str(snapshot.id),
        "confirmation_required_text": "CONFIRM",
    }


@router.post("/{campaign_id}/test-send", response_model=dict)
async def test_send_campaign(
    campaign_id: str,
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")
    to_phone_e164 = str(payload.get("to_phone_e164") or "").strip()
    if not to_phone_e164:
        raise BadRequestException("to_phone_e164 is required")
    test_key = f"campaign:{campaign.id}:test:{to_phone_e164}:{campaign.template_id or 'none'}"
    row = MessageOutbox(
        business_id=actor.business.id,
        campaign_id=campaign.id,
        campaign_recipient_id=None,
        conversation_id=None,
        phone_number_id=campaign.phone_number_id or "",
        to_phone_e164=to_phone_e164,
        message_type="template" if campaign.template_id else "text",
        template_id=campaign.template_id,
        payload_json={
            "to_phone_e164": to_phone_e164,
            "template_id": str(campaign.template_id) if campaign.template_id else None,
            "variables": payload.get("variables") or {},
            "text": payload.get("text"),
            "is_test_send": True,
            "campaign_id": str(campaign.id),
            "source": "test_send",
        },
        source_type="test_send",
        priority=50,
        scheduled_at=datetime.now(timezone.utc),
        idempotency_key=test_key,
        status="pending",
        attempt_count=0,
    )
    db.add(row)
    await db.commit()
    return {"status": "queued", "message_outbox_id": str(row.id)}


@router.post("/{campaign_id}/pause", response_model=CampaignTransitionResponse)
async def pause_campaign(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    campaign = await CampaignPauseService(db).pause_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        reason="manual_pause",
    )
    await db.commit()
    return CampaignTransitionResponse(
        campaign_id=campaign.id,
        status=campaign.status,
        updated_at=campaign.updated_at,
    )


@router.post("/{campaign_id}/resume", response_model=CampaignTransitionResponse)
async def resume_campaign(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    campaign = await CampaignResumeService(db).resume_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        reason="manual_resume",
    )
    await db.commit()
    return CampaignTransitionResponse(
        campaign_id=campaign.id,
        status=campaign.status,
        updated_at=campaign.updated_at,
    )


@router.post("/{campaign_id}/cancel", response_model=CampaignTransitionResponse)
async def cancel_campaign(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    campaign = await CampaignCancelService(db).cancel_campaign(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        reason="manual_cancel",
    )
    await db.commit()
    return CampaignTransitionResponse(
        campaign_id=campaign.id,
        status=campaign.status,
        updated_at=campaign.updated_at,
    )


@router.get("/{campaign_id}/recipients/{recipient_id}", response_model=dict)
async def get_campaign_recipient_state(
    campaign_id: str,
    recipient_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    svc = CampaignStateService(db)
    recipient, allowed_next = await svc.get_campaign_recipient_with_allowed_next(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        campaign_recipient_id=UUID(recipient_id),
    )
    return {
        "recipient_id": str(recipient.id),
        "campaign_id": str(recipient.campaign_id),
        "status": recipient.status,
        "allowed_next_statuses": allowed_next,
        "updated_at": recipient.updated_at.isoformat(),
    }


@router.post("/{campaign_id}/recipients/{recipient_id}/transition", response_model=CampaignRecipientTransitionResponse)
async def transition_campaign_recipient(
    campaign_id: str,
    recipient_id: str,
    payload: CampaignRecipientTransitionRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = CampaignStateService(db)
    recipient = await svc.transition_campaign_recipient(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
        campaign_recipient_id=UUID(recipient_id),
        new_status=payload.to_status,
    )
    await db.commit()
    return CampaignRecipientTransitionResponse(
        recipient_id=recipient.id,
        status=recipient.status,
        updated_at=recipient.updated_at,
    )


@router.get("/{campaign_id}/snapshot-items/{snapshot_item_id}", response_model=dict)
async def get_campaign_snapshot_item_state(
    campaign_id: str,
    snapshot_item_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    del campaign_id, actor
    svc = CampaignStateService(db)
    item, allowed_next = await svc.get_snapshot_item_with_allowed_next(
        recipient_item_id=UUID(snapshot_item_id),
    )
    return {
        "snapshot_item_id": str(item.id),
        "status": item.status,
        "allowed_next_statuses": allowed_next,
        "updated_at": item.updated_at.isoformat(),
    }


@router.get("/recipient-events", response_model=list[dict])
async def list_campaign_recipient_events(
    campaign_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    scheduled_at: datetime | None = Query(default=None),
    locked_until: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    # status/scheduled_at/locked_until are accepted for filter-API shape parity; only status maps here.
    del scheduled_at, locked_until
    stmt = select(CampaignRecipientEvent).where(
        CampaignRecipientEvent.business_id == actor.business.id,
        CampaignRecipientEvent.deleted_at.is_(None),
    )
    if campaign_id is not None:
        stmt = stmt.where(CampaignRecipientEvent.campaign_id == campaign_id)
    if status is not None:
        stmt = stmt.where(CampaignRecipientEvent.new_status == status.lower())
    stmt = stmt.order_by(CampaignRecipientEvent.created_at.desc(), CampaignRecipientEvent.id.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "campaign_id": str(r.campaign_id),
            "campaign_recipient_id": str(r.campaign_recipient_id),
            "event_type": r.event_type,
            "old_status": r.old_status,
            "new_status": r.new_status,
            "provider_message_id": r.provider_message_id,
            "payload_json": r.payload_json or {},
            "error_code": r.error_code,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/send-jobs", response_model=list[dict])
async def list_campaign_send_jobs(
    campaign_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    scheduled_at: datetime | None = Query(default=None),
    locked_until: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CampaignSendJob).where(
        CampaignSendJob.business_id == actor.business.id,
        CampaignSendJob.deleted_at.is_(None),
    )
    if campaign_id is not None:
        stmt = stmt.where(CampaignSendJob.campaign_id == campaign_id)
    if status is not None:
        stmt = stmt.where(CampaignSendJob.status == status.lower())
    if scheduled_at is not None:
        stmt = stmt.where(CampaignSendJob.scheduled_at <= scheduled_at)
    if locked_until is not None:
        stmt = stmt.where(CampaignSendJob.locked_until <= locked_until)
    stmt = stmt.order_by(CampaignSendJob.scheduled_at.asc(), CampaignSendJob.id.asc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "campaign_id": str(r.campaign_id),
            "campaign_recipient_id": str(r.campaign_recipient_id),
            "business_id": str(r.business_id),
            "phone_number_id": r.phone_number_id,
            "status": r.status,
            "locked_by": r.locked_by,
            "locked_until": r.locked_until.isoformat() if r.locked_until else None,
            "attempt_count": r.attempt_count,
            "scheduled_at": r.scheduled_at.isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "failed_at": r.failed_at.isoformat() if r.failed_at else None,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{campaign_id}/recipients", response_model=dict)
async def list_campaign_recipients(
    campaign_id: str,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="asc"),
    request_query_fingerprint: str | None = Query(default=None, alias="queryFingerprint"),
    limit: int = Query(default=500, ge=1, le=5000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign_uuid = UUID(campaign_id)
    sort_by, sort_dir, limit = validate_table_query(
        table="campaign_recipients",
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        filters={"status": status, "search": search},
    )
    stmt = select(CampaignRecipient).where(
        CampaignRecipient.business_id == actor.business.id,
        CampaignRecipient.campaign_id == campaign_uuid,
        CampaignRecipient.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(CampaignRecipient.status == status.lower())
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(or_(CampaignRecipient.name.ilike(q), CampaignRecipient.phone_e164.ilike(q), CampaignRecipient.status.ilike(q)))
    sort_map = {
        "updated_at": CampaignRecipient.updated_at,
        "sent_at": CampaignRecipient.sent_at,
        "status": CampaignRecipient.status,
    }
    sort_key = sort_map.get(sort_by, CampaignRecipient.updated_at)
    query_risk = classify_table_query(
        table="campaign_recipients",
        sort_by=sort_by,
        limit=limit,
        filters={"status": status, "search": search},
    )
    sort_desc = str(sort_dir).lower() != "asc"
    computed_query_fingerprint = _campaign_recipient_query_fingerprint(
        business_id=actor.business.id,
        campaign_id=campaign_uuid,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    if request_query_fingerprint is not None and request_query_fingerprint != computed_query_fingerprint:
        raise HTTPException(status_code=400, detail={"code": "CURSOR_QUERY_MISMATCH", "message": "Query fingerprint mismatch"})
    if cursor:
        try:
            payload = decode_cursor(cursor)
            if payload.get("resource") != "campaign_recipients":
                raise InvalidCursorError("Cursor resource mismatch")
            if str(payload.get("businessId")) != str(actor.business.id):
                raise InvalidCursorError("Cursor business mismatch")
            if str(payload.get("campaignId")) != str(campaign_uuid):
                raise InvalidCursorError("Cursor campaign mismatch")
            if payload.get("queryFingerprint") != computed_query_fingerprint:
                raise InvalidCursorError("CURSOR_QUERY_MISMATCH")
            cursor_id = UUID(str(payload.get("id")))
            cursor_val = payload.get("sortValue")
            if sort_by in {"updated_at", "sent_at"} and cursor_val is not None:
                cursor_val = datetime.fromisoformat(str(cursor_val))
            if cursor_val is not None:
                if sort_desc:
                    stmt = stmt.where(or_(sort_key < cursor_val, and_(sort_key == cursor_val, CampaignRecipient.id < cursor_id)))
                else:
                    stmt = stmt.where(or_(sort_key > cursor_val, and_(sort_key == cursor_val, CampaignRecipient.id > cursor_id)))
        except (InvalidCursorError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CURSOR", "message": str(exc)}) from exc
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    order_primary = sort_key.desc() if sort_desc else sort_key.asc()
    order_secondary = CampaignRecipient.id.desc() if sort_desc else CampaignRecipient.id.asc()
    rows = (await db.execute(stmt.order_by(order_primary, order_secondary).limit(limit + 1))).scalars().all()
    page_rows = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page_rows:
        last = page_rows[-1]
        sort_value = getattr(last, sort_by, None)
        if sort_by not in {"updated_at", "sent_at", "status"}:
            sort_value = last.updated_at
        if hasattr(sort_value, "isoformat"):
            sort_value = sort_value.isoformat()
        next_cursor = encode_cursor(
            {
                "resource": "campaign_recipients",
                "businessId": str(actor.business.id),
                "campaignId": str(campaign_uuid),
                "queryFingerprint": computed_query_fingerprint,
                "sortKey": sort_by,
                "sortDir": sort_dir,
                "sortValue": sort_value,
                "id": str(last.id),
            }
        )
    items = [
        {
            "id": str(r.id),
            "name": r.name,
            "status": r.status,
            "eligibility_status": r.eligibility_status,
            "eligibility_reason": r.eligibility_reason,
            "phone_e164": (r.phone_e164 if ("*" in actor.permissions or "campaigns:columns:phone" in actor.permissions) else None),
            "provider_message_id": r.provider_message_id,
            "attempt_count": r.attempt_count,
            "actual_cost": (r.actual_cost if ("*" in actor.permissions or "campaigns:columns:cost" in actor.permissions) else None),
            "last_error_code": (r.last_error_code if ("*" in actor.permissions or "campaigns:columns:errors" in actor.permissions) else None),
            "last_error_message": (r.last_error_message if ("*" in actor.permissions or "campaigns:columns:errors" in actor.permissions) else None),
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
            "read_at": r.read_at.isoformat() if r.read_at else None,
            "failed_at": r.failed_at.isoformat() if r.failed_at else None,
        }
        for r in page_rows
    ]
    return {
        "items": items,
        "next_cursor": next_cursor,
        "total": total,
        "query_fingerprint": computed_query_fingerprint,
        "query_risk_class": query_risk.risk_class,
        "query_risk_reasons": query_risk.reasons,
        "freshness": freshness_live_db(),
    }


@router.get("/{campaign_id}/recipient-explainability", response_model=list[dict])
async def list_campaign_recipient_explainability(
    campaign_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CampaignRecipient).where(
        CampaignRecipient.business_id == actor.business.id,
        CampaignRecipient.campaign_id == UUID(campaign_id),
        CampaignRecipient.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(CampaignRecipient.status == status.lower())
    rows = (await db.execute(stmt.order_by(CampaignRecipient.created_at.asc()).limit(limit))).scalars().all()
    svc = CampaignRecipientExplainabilityService(db)
    output: list[dict] = []
    for row in rows:
        output.append(
            await svc.explain_recipient(
                business_id=actor.business.id,
                campaign_id=UUID(campaign_id),
                recipient=row,
            )
        )
    return output


@router.get("/{campaign_id}/events", response_model=list[dict])
async def list_campaign_events(
    campaign_id: str,
    limit: int = Query(default=1000, ge=1, le=5000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    recipient_events = (
        await db.execute(
            select(CampaignRecipientEvent).where(
                CampaignRecipientEvent.business_id == actor.business.id,
                CampaignRecipientEvent.campaign_id == UUID(campaign_id),
                CampaignRecipientEvent.deleted_at.is_(None),
            ).order_by(CampaignRecipientEvent.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    status_events = (
        await db.execute(
            select(CampaignStatusEvent).where(
                CampaignStatusEvent.campaign_id == UUID(campaign_id),
                CampaignStatusEvent.deleted_at.is_(None),
            ).order_by(CampaignStatusEvent.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    events = [
        {
            "kind": "recipient_event",
            "id": str(e.id),
            "event_type": e.event_type,
            "old_status": e.old_status,
            "new_status": e.new_status,
            "payload_json": e.payload_json or {},
            "created_at": e.created_at.isoformat(),
        }
        for e in recipient_events
    ] + [
        {
            "kind": "campaign_status_event",
            "id": str(e.id),
            "old_status": e.old_status,
            "new_status": e.new_status,
            "reason": e.reason,
            "created_at": e.created_at.isoformat(),
        }
        for e in status_events
    ]
    events.sort(key=lambda x: x["created_at"], reverse=True)
    return events[:limit]


@router.get("/{campaign_id}/blackbox", response_model=list[dict])
async def get_campaign_blackbox_timeline(
    campaign_id: str,
    limit: int = Query(default=1000, ge=1, le=5000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(CampaignExecutionEvent).where(
                CampaignExecutionEvent.business_id == actor.business.id,
                CampaignExecutionEvent.campaign_id == UUID(campaign_id),
                CampaignExecutionEvent.deleted_at.is_(None),
            ).order_by(CampaignExecutionEvent.observed_at.desc(), CampaignExecutionEvent.id.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "campaign_id": str(r.campaign_id),
            "event_type": r.event_type,
            "message": r.message,
            "payload_json": r.payload_json or {},
            "observed_at": r.observed_at.isoformat(),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{campaign_id}/auto-pause-options", response_model=dict)
async def get_campaign_auto_pause_options(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")

    latest_auto_pause = (
        await db.execute(
            select(CampaignExecutionEvent).where(
                CampaignExecutionEvent.business_id == actor.business.id,
                CampaignExecutionEvent.campaign_id == campaign.id,
                CampaignExecutionEvent.event_type == "campaign_auto_paused",
                CampaignExecutionEvent.deleted_at.is_(None),
            ).order_by(CampaignExecutionEvent.observed_at.desc(), CampaignExecutionEvent.id.desc()).limit(1)
        )
    ).scalar_one_or_none()

    return {
        "campaign_id": str(campaign.id),
        "status": campaign.status,
        "latest_auto_pause": (
            {
                "event_type": latest_auto_pause.event_type,
                "message": latest_auto_pause.message,
                "payload_json": latest_auto_pause.payload_json or {},
                "observed_at": latest_auto_pause.observed_at.isoformat(),
            }
            if latest_auto_pause
            else None
        ),
        "options": [
            {"action": "resume_slowly", "endpoint": f"/api/v1/campaigns/{campaign.id}/resume", "hint": "Temporarily lower RATE_LIMIT_CAMPAIGN_MPS before resume"},
            {"action": "resume_normally", "endpoint": f"/api/v1/campaigns/{campaign.id}/resume", "hint": "Resume with current limiter defaults"},
            {"action": "cancel_remaining", "endpoint": f"/api/v1/campaigns/{campaign.id}/cancel", "hint": "Cancel unsent recipients"},
            {"action": "export_failed_recipients", "endpoint": f"/api/v1/campaigns/{campaign.id}/recipients?status=failed", "hint": "Download failed recipients from export/reporting flow"},
            {"action": "send_to_support", "endpoint": f"/api/v1/campaigns/{campaign.id}/blackbox", "hint": "Share blackbox timeline + auto-pause payload with support"},
        ],
    }


@router.get("/{campaign_id}/audience-warmth", response_model=dict)
async def get_campaign_audience_warmth(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await AudienceWarmthService(db).score_campaign_audience(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    return result


@router.get("/{campaign_id}/health-score", response_model=dict)
async def get_campaign_health_score(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await CampaignHealthService(db).get_health(
        business_id=actor.business.id,
        campaign_id=UUID(campaign_id),
    )
    return result


@router.get("/{campaign_id}/segment-diagnostics", response_model=dict)
async def get_campaign_segment_diagnostics(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign_uuid = UUID(campaign_id)
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == campaign_uuid,
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")

    rows = (
        await db.execute(
            select(CampaignRecipient, Contact)
            .outerjoin(
                Contact,
                and_(
                    Contact.id == CampaignRecipient.contact_id,
                    Contact.business_id == actor.business.id,
                    Contact.deleted_at.is_(None),
                ),
            )
            .where(
                CampaignRecipient.business_id == actor.business.id,
                CampaignRecipient.campaign_id == campaign_uuid,
                CampaignRecipient.deleted_at.is_(None),
            )
        )
    ).all()

    original_count = len(rows)
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=180)
    complain_cutoff = now - timedelta(days=90)

    unclear_opt_in: set[str] = set()
    stale_engagement: set[str] = set()
    complained_or_refunded: set[str] = set()
    outside_area: set[str] = set()
    contact_ids: set[UUID] = set()
    recipient_contact_map: dict[str, UUID] = {}

    for recipient, contact in rows:
        rid = str(recipient.id)
        if recipient.contact_id:
            recipient_contact_map[rid] = recipient.contact_id
            contact_ids.add(recipient.contact_id)
        if not contact:
            unclear_opt_in.add(rid)
            continue

        if str(contact.opt_in_status or "").lower() != "opted_in" or contact.opt_in_timestamp is None:
            unclear_opt_in.add(rid)

        last_engaged_at = contact.last_seen_at or contact.last_message_at
        if last_engaged_at is None or last_engaged_at < stale_cutoff:
            stale_engagement.add(rid)

        tags = [str(t).strip().lower() for t in (contact.tags or []) if str(t).strip()]
        attrs = contact.custom_attributes or {}
        complaint_flag = (
            any(tag in {"complaint", "complained", "refund", "refunded", "chargeback", "dispute"} for tag in tags)
            or bool(attrs.get("complaint"))
            or bool(attrs.get("refund"))
            or bool(attrs.get("chargeback"))
        )
        if complaint_flag and contact.updated_at >= complain_cutoff:
            complained_or_refunded.add(rid)

        outside_flag = (
            bool(attrs.get("outside_delivery_area"))
            or bool(attrs.get("out_of_delivery_area"))
            or (attrs.get("delivery_area_allowed") is False)
            or ("outside_delivery_area" in tags)
            or ("out_of_area" in tags)
        )
        if outside_flag:
            outside_area.add(rid)

    ignored_contact_ids: set[UUID] = set()
    if contact_ids:
        ignored_rows = (
            await db.execute(
                select(
                    CampaignRecipient.contact_id,
                    func.count(CampaignRecipient.id),
                )
                .where(
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.contact_id.in_(list(contact_ids)),
                    CampaignRecipient.campaign_id != campaign_uuid,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.status.in_(["sent", "delivered", "read", "failed", "skipped"]),
                    CampaignRecipient.replied_at.is_(None),
                )
                .group_by(CampaignRecipient.contact_id)
                .having(func.count(CampaignRecipient.id) >= 3)
            )
        ).all()
        ignored_contact_ids = {cid for cid, _ in ignored_rows if cid is not None}

    ignored_campaigns: set[str] = set()
    for rid, contact_id in recipient_contact_map.items():
        if contact_id in ignored_contact_ids:
            ignored_campaigns.add(rid)

    risky_recipients = unclear_opt_in | stale_engagement | ignored_campaigns | complained_or_refunded | outside_area
    safe_audience = max(0, original_count - len(risky_recipients))
    expected_revenue_loss = "low" if len(risky_recipients) <= max(1, int(original_count * 0.6)) else "medium"
    quality_risk_reduction = "high" if len(risky_recipients) >= max(1, int(original_count * 0.2)) else "medium"

    return {
        "campaign_id": str(campaign_uuid),
        "original_count": original_count,
        "safe_audience_count": safe_audience,
        "expected_revenue_loss": expected_revenue_loss,
        "quality_risk_reduction": quality_risk_reduction,
        "issues": {
            "unclear_opt_in": len(unclear_opt_in),
            "stale_engagement_180d": len(stale_engagement),
            "ignored_3plus_campaigns": len(ignored_campaigns),
            "complained_or_refunded_recently": len(complained_or_refunded),
            "outside_delivery_area": len(outside_area),
        },
    }


@router.get("/{campaign_id}/whatsapp-health", response_model=dict)
async def get_campaign_whatsapp_health_dashboard(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")

    phone = (
        await db.execute(
            select(WhatsAppPhoneNumber).where(
                WhatsAppPhoneNumber.business_id == actor.business.id,
                WhatsAppPhoneNumber.phone_number_id == campaign.phone_number_id,
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    template = None
    if campaign.template_id is not None:
        template = (
            await db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.id == campaign.template_id,
                    WhatsAppMessageTemplate.business_id == actor.business.id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)
    total_recent = int(
        (
            await db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.updated_at >= window_start,
                    CampaignRecipient.status.in_(["sent", "delivered", "read", "replied", "failed"]),
                )
            )
        ).scalar_one()
        or 0
    )
    failed_recent = int(
        (
            await db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.failed_at.is_not(None),
                    CampaignRecipient.failed_at >= window_start,
                )
            )
        ).scalar_one()
        or 0
    )
    unsubscribe_recent = int(
        (
            await db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.updated_at >= window_start,
                    (
                        CampaignRecipient.eligibility_reason.ilike("%opted_out%")
                        | CampaignRecipient.eligibility_reason.ilike("%unsubscribed%")
                    ),
                )
            )
        ).scalar_one()
        or 0
    )
    blocked_recent = int(
        (
            await db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.updated_at >= window_start,
                    (
                        CampaignRecipient.eligibility_reason.ilike("%blocked%")
                        | CampaignRecipient.last_error_code.in_(["131047", "131048"])
                    ),
                )
            )
        ).scalar_one()
        or 0
    )

    failure_rate = (float(failed_recent) / float(total_recent)) if total_recent > 0 else 0.0
    unsubscribe_rate = (float(unsubscribe_recent) / float(total_recent)) if total_recent > 0 else 0.0
    blocked_rate = (float(blocked_recent) / float(total_recent)) if total_recent > 0 else 0.0

    last_webhook = (
        await db.execute(
            select(WebhookEvent.received_at)
            .where(
                WebhookEvent.business_id == actor.business.id,
                WebhookEvent.provider == "whatsapp",
                WebhookEvent.deleted_at.is_(None),
            )
            .order_by(WebhookEvent.received_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    webhook_lag_seconds = int((now - last_webhook).total_seconds()) if last_webhook is not None else None
    if webhook_lag_seconds is None:
        webhook_lag_label = "Unknown"
    elif webhook_lag_seconds <= 180:
        webhook_lag_label = "Normal"
    elif webhook_lag_seconds <= 600:
        webhook_lag_label = "Elevated"
    else:
        webhook_lag_label = "Delayed"

    active_pipeline = int(
        (
            await db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.deleted_at.is_(None),
                    CampaignRecipient.status.in_(["pending", "queued", "sending", "reserved", "unknown_retryable"]),
                )
            )
        ).scalar_one()
        or 0
    )
    total_recipients = max(1, int(campaign.total_recipients or 0))
    pressure_ratio = float(active_pipeline) / float(total_recipients)
    pressure_score = min(
        100,
        int(
            (failure_rate * 380)
            + (unsubscribe_rate * 300)
            + (blocked_rate * 300)
            + (pressure_ratio * 30)
            + (0 if webhook_lag_label == "Normal" else (8 if webhook_lag_label == "Elevated" else 16 if webhook_lag_label == "Delayed" else 6))
        ),
    )

    quality = (phone.quality_rating or "unknown") if phone else "unknown"
    quality_lower = quality.lower()
    if quality_lower in {"green", "high"}:
        health_bucket = "Safe"
    elif quality_lower in {"yellow", "medium"} or pressure_score >= 45:
        health_bucket = "Caution"
    else:
        health_bucket = "Risk"
    if quality_lower in {"red", "low"} or failure_rate >= 0.10 or blocked_rate >= 0.03:
        health_bucket = "Risk"

    template_quality_display = "Unknown"
    if template is not None:
        tq = (template.quality_rating or "").strip()
        ts = (template.status or "").strip()
        template_quality_display = tq if tq else ts if ts else "Unknown"

    recommendation = "Safe to run campaigns"
    if health_bucket == "Caution":
        recommendation = "Run with SLOW_START and monitor every 5 minutes"
    if health_bucket == "Risk":
        recommendation = "Pause marketing campaigns and fix health signals first"

    return {
        "campaign_id": str(campaign.id),
        "phone_number_health": health_bucket,
        "quality": quality if quality else "unknown",
        "messaging_tier": (phone.messaging_limit_tier if phone and phone.messaging_limit_tier else "unknown"),
        "template_quality": template_quality_display,
        "recent_failure_rate": round(failure_rate * 100, 2),
        "recent_unsubscribe_rate": round(unsubscribe_rate * 100, 2),
        "recent_block_report_rate": round(blocked_rate * 100, 2),
        "webhook_lag": webhook_lag_label,
        "webhook_lag_seconds": webhook_lag_seconds,
        "campaign_pressure_score": pressure_score,
        "recommended_action": recommendation,
        "window_hours": 24,
        "signals": {
            "recent_sample_size": total_recent,
            "failed_recent": failed_recent,
            "unsubscribe_recent": unsubscribe_recent,
            "blocked_report_recent": blocked_recent,
            "active_pipeline_recipients": active_pipeline,
        },
    }


@router.get("/{campaign_id}/analytics", response_model=dict)
async def get_campaign_analytics(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("Campaign not found")
    return {
        "campaign_id": str(row.id),
        "status": row.status,
        "campaign_execution_mode": _campaign_execution_mode(row),
        "execution_mode": _execution_mode(row),
        "total_recipients": row.total_recipients,
        "eligible_recipients": row.eligible_recipients,
        "skipped_recipients": row.skipped_recipients,
        "sent_count": row.sent_count,
        "delivered_count": row.delivered_count,
        "read_count": row.read_count,
        "replied_count": row.replied_count,
        "failed_count": row.failed_count,
        "estimated_cost": row.estimated_cost,
        "actual_cost": row.actual_cost,
    }


@router.get("/{campaign_id}/export", response_model=dict)
async def export_campaign(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")
    recipients = (
        await db.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.business_id == actor.business.id,
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.deleted_at.is_(None),
            ).order_by(CampaignRecipient.created_at.asc(), CampaignRecipient.id.asc())
        )
    ).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    header = [
            "campaign_id",
            "recipient_id",
            "phone_e164",
            "status",
            "eligibility_status",
            "eligibility_reason",
            "provider_message_id",
            "attempt_count",
            "sent_at",
            "delivered_at",
            "read_at",
            "failed_at",
            "last_error_code",
            "last_error_message",
        ]
    writer.writerow([escape_csv_cell(c) for c in header])
    for r in recipients:
        writer.writerow(
            [escape_csv_cell(v) for v in [
                str(campaign.id),
                str(r.id),
                r.phone_e164,
                r.status,
                r.eligibility_status,
                r.eligibility_reason or "",
                r.provider_message_id or "",
                int(r.attempt_count or 0),
                r.sent_at.isoformat() if r.sent_at else "",
                r.delivered_at.isoformat() if r.delivered_at else "",
                r.read_at.isoformat() if r.read_at else "",
                r.failed_at.isoformat() if r.failed_at else "",
                r.last_error_code or "",
                r.last_error_message or "",
            ]]
        )
    content = buf.getvalue().encode("utf-8")
    key = object_storage_service.put_bytes(
        namespace="campaign_exports",
        filename_hint=f"campaign_{campaign.id}.csv",
        content=content,
    )
    return {
        "campaign_id": str(campaign.id),
        "status": "ready",
        "format": "csv",
        "download_url": object_storage_service.build_url(key),
        "storage_key": key,
        "rows": len(recipients),
    }


@router.post("/{campaign_id}/export-jobs", response_model=dict)
async def create_campaign_export_job(
    campaign_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")

    operation_id = f"campaign_export:{campaign.id}:{datetime.now(timezone.utc).isoformat()}"
    job = JobOperation(
        business_id=actor.business.id,
        operation_id=operation_id,
        actor_user_id=actor.user.id,
        idempotency_key=operation_id,
        payload_json={
            "campaign_id": str(campaign.id),
            "status": "pending",
            "progress": 5,
            "download_url": None,
            "storage_key": None,
            "rows": 0,
        },
        status="pending",
    )
    db.add(job)
    await db.flush()
    db.add(
        OutboxEvent(
            business_id=actor.business.id,
            campaign_id=campaign.id,
            operation_id=operation_id,
            event_type="campaign_export.process_job",
            payload_json={
                "job_operation_id": str(job.id),
                "campaign_id": str(campaign.id),
            },
            status="pending",
        )
    )
    await db.commit()
    await db.refresh(job)
    return {
        "job_id": str(job.id),
        "campaign_id": str(campaign.id),
        "status": "pending",
        "progress": 5,
    }


@router.get("/{campaign_id}/export-jobs/{job_id}", response_model=dict)
async def get_campaign_export_job(
    campaign_id: str,
    job_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == UUID(campaign_id),
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not campaign:
        raise NotFoundException("Campaign not found")

    job = (
        await db.execute(
            select(JobOperation).where(
                JobOperation.id == UUID(job_id),
                JobOperation.business_id == actor.business.id,
                JobOperation.deleted_at.is_(None),
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not job:
        raise NotFoundException("Export job not found")

    payload = dict(job.payload_json or {})
    payload_campaign_id = str(payload.get("campaign_id") or "")
    if payload_campaign_id != str(campaign.id):
        raise NotFoundException("Export job not found for this campaign")

    return {
        "job_id": str(job.id),
        "campaign_id": str(campaign.id),
        "status": str(payload.get("status") or job.status),
        "progress": int(payload.get("progress") or (100 if job.status == "completed" else 5)),
        "download_url": payload.get("download_url"),
        "storage_key": payload.get("storage_key"),
        "rows": int(payload.get("rows") or 0),
    }


@router.post("/{campaign_id}/snapshot-items/{snapshot_item_id}/transition", response_model=CampaignRecipientTransitionResponse)
async def transition_campaign_snapshot_item(
    campaign_id: str,
    snapshot_item_id: str,
    payload: CampaignRecipientTransitionRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    del campaign_id, actor
    svc = CampaignStateService(db)
    item = await svc.transition_recipient_item(
        recipient_item_id=UUID(snapshot_item_id),
        new_status=payload.to_status,
    )
    await db.commit()
    return CampaignRecipientTransitionResponse(
        recipient_id=item.id,
        status=item.status,
        updated_at=item.updated_at,
    )

from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.models.business_domains import WhatsAppMessageTemplate
from app.models.business_domains import ProviderSyncRun
from app.schemas.template import (
    TemplateCreateRequest,
    TemplateResponse,
    TemplateSyncRequest,
    TemplateSyncResponse,
    TemplateSyncRunResponse,
    TemplateStatusUpdateRequest,
    TemplateSummaryResponse,
)
from app.services.template_graph_sync_service import TemplateGraphSyncService

router = APIRouter(prefix="/templates", tags=["Templates"])


def _to_template_response(row: WhatsAppMessageTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=row.id,
        waba_id=row.waba_id,
        meta_template_id=row.meta_template_id,
        name=row.name,
        language=row.language,
        category=row.category,
        status=row.status,
        components_json=row.components_json or {},
        rejection_reason=row.rejection_reason,
        last_synced_at=row.last_synced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    language: str | None = Query(default=None),
    waba_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sendable_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    # Keep template catalog provider-authoritative by opportunistically syncing when empty/stale.
    latest_sync = (
        await db.execute(
            select(func.max(WhatsAppMessageTemplate.last_synced_at)).where(
                WhatsAppMessageTemplate.business_id == actor.business.id,
                WhatsAppMessageTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if latest_sync is None or latest_sync < (datetime.now(timezone.utc) - timedelta(minutes=30)):
        try:
            await TemplateGraphSyncService(db).sync_business_templates(
                business_id=actor.business.id,
                requested_by_user_id=actor.user.id,
                trigger="templates_list_auto_sync",
            )
        except Exception:
            # Read path should degrade gracefully; sync failures are tracked in provider sync runs and ledger.
            await db.rollback()

    stmt = select(WhatsAppMessageTemplate).where(
        WhatsAppMessageTemplate.business_id == actor.business.id,
        WhatsAppMessageTemplate.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(WhatsAppMessageTemplate.status == status.strip().lower())
    if category:
        stmt = stmt.where(WhatsAppMessageTemplate.category == category.strip().lower())
    if language:
        stmt = stmt.where(WhatsAppMessageTemplate.language == language.strip())
    if waba_id:
        stmt = stmt.where(WhatsAppMessageTemplate.waba_id == waba_id.strip())
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            WhatsAppMessageTemplate.name.ilike(q)
            | WhatsAppMessageTemplate.meta_template_id.ilike(q)
        )
    if sendable_only:
        stmt = stmt.where(WhatsAppMessageTemplate.status.in_(["approved", "active"]))

    stmt = stmt.order_by(WhatsAppMessageTemplate.created_at.desc(), WhatsAppMessageTemplate.id.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_template_response(r) for r in rows]


@router.get("/summary", response_model=TemplateSummaryResponse)
async def get_template_summary(
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await TemplateGraphSyncService(db).sync_business_templates(
            business_id=actor.business.id,
            requested_by_user_id=actor.user.id,
            trigger="templates_summary_auto_sync",
        )
    except Exception:
        await db.rollback()

    base = (
        select(WhatsAppMessageTemplate)
        .where(
            WhatsAppMessageTemplate.business_id == actor.business.id,
            WhatsAppMessageTemplate.deleted_at.is_(None),
        )
        .subquery()
    )
    total = int((await db.execute(select(func.count()).select_from(base))).scalar_one() or 0)
    approved_or_active = int(
        (
            await db.execute(
                select(func.count()).select_from(base).where(base.c.status.in_(["approved", "active"]))
            )
        ).scalar_one()
        or 0
    )
    pending_or_in_review = int(
        (
            await db.execute(
                select(func.count()).select_from(base).where(base.c.status.in_(["pending", "in_review", "submitted"]))
            )
        ).scalar_one()
        or 0
    )
    rejected_or_paused = int(
        (
            await db.execute(
                select(func.count()).select_from(base).where(base.c.status.in_(["rejected", "paused", "disabled"]))
            )
        ).scalar_one()
        or 0
    )
    draft_or_unknown = max(0, total - approved_or_active - pending_or_in_review - rejected_or_paused)
    return TemplateSummaryResponse(
        total=total,
        approved_or_active=approved_or_active,
        pending_or_in_review=pending_or_in_review,
        rejected_or_paused=rejected_or_paused,
        draft_or_unknown=draft_or_unknown,
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        template_uuid = UUID(template_id)
    except ValueError as exc:
        raise BadRequestException("Invalid template id") from exc

    row = (
        await db.execute(
            select(WhatsAppMessageTemplate).where(
                WhatsAppMessageTemplate.id == template_uuid,
                WhatsAppMessageTemplate.business_id == actor.business.id,
                WhatsAppMessageTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("Template not found")
    return _to_template_response(row)


@router.post("", response_model=TemplateResponse)
async def create_template(
    payload: TemplateCreateRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    normalized_status = payload.status.strip().lower()
    if normalized_status not in {"draft", "pending", "in_review", "submitted", "approved", "active", "rejected", "paused"}:
        raise BadRequestException("Invalid template status")

    row = WhatsAppMessageTemplate(
        business_id=actor.business.id,
        waba_id=payload.waba_id.strip(),
        meta_template_id=(payload.meta_template_id.strip() if payload.meta_template_id else None),
        name=payload.name.strip(),
        language=payload.language.strip(),
        category=(payload.category.strip().lower() if payload.category else None),
        status=normalized_status,
        components_json=payload.components_json or {},
        rejection_reason=(payload.rejection_reason.strip() if payload.rejection_reason else None),
        last_synced_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_template_response(row)


@router.patch("/{template_id}/status", response_model=TemplateResponse)
async def update_template_status(
    template_id: str,
    payload: TemplateStatusUpdateRequest,
    actor: CurrentActor = Depends(require_permissions("campaigns:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        template_uuid = UUID(template_id)
    except ValueError as exc:
        raise BadRequestException("Invalid template id") from exc

    row = (
        await db.execute(
            select(WhatsAppMessageTemplate).where(
                WhatsAppMessageTemplate.id == template_uuid,
                WhatsAppMessageTemplate.business_id == actor.business.id,
                WhatsAppMessageTemplate.deleted_at.is_(None),
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("Template not found")

    normalized_status = payload.status.strip().lower()
    if normalized_status not in {"draft", "pending", "in_review", "submitted", "approved", "active", "rejected", "paused", "disabled"}:
        raise BadRequestException("Invalid template status")

    row.status = normalized_status
    row.rejection_reason = payload.rejection_reason.strip() if payload.rejection_reason else None
    row.last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _to_template_response(row)


@router.post("/sync", response_model=TemplateSyncResponse)
async def sync_templates_from_graph(
    payload: TemplateSyncRequest,
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
    db: AsyncSession = Depends(get_db),
):
    result = await TemplateGraphSyncService(db).sync_business_templates(
        business_id=actor.business.id,
        requested_by_user_id=actor.user.id,
        trigger="manual_endpoint",
        waba_id=(payload.waba_id.strip() if payload.waba_id else None),
    )
    return TemplateSyncResponse(
        run_id=result.run_id,
        business_id=result.business_id,
        status=result.status,
        waba_ids=result.waba_ids,
        templates_fetched=result.templates_fetched,
        templates_upserted=result.templates_upserted,
        templates_marked_deleted=result.templates_marked_deleted,
        completed_at=result.completed_at,
        failure_reason=result.failure_reason,
    )


@router.get("/sync/runs", response_model=list[TemplateSyncRunResponse])
async def list_template_sync_runs(
    limit: int = Query(default=20, ge=1, le=100),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(ProviderSyncRun)
            .where(
                ProviderSyncRun.business_id == actor.business.id,
                ProviderSyncRun.provider == "meta",
                ProviderSyncRun.sync_type == "whatsapp_templates",
                ProviderSyncRun.deleted_at.is_(None),
            )
            .order_by(ProviderSyncRun.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        TemplateSyncRunResponse(
            run_id=r.id,
            provider=r.provider,
            sync_type=r.sync_type,
            status=r.status,
            started_at=r.started_at,
            completed_at=r.completed_at,
            failure_reason=r.failure_reason,
        )
        for r in rows
    ]

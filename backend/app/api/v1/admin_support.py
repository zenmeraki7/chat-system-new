from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.database import get_db
from app.models.business_domains import (
    AdminAccessAuditLog,
    AdminAccessGrant,
    AuditLog,
    BusinessEvent,
    OutboxEvent,
    ProviderWebhookEvent,
    WebhookEvent,
)

router = APIRouter(prefix="/admin-support", tags=["Admin Support"])


@router.post("/activity/client-events", response_model=dict)
async def ingest_client_activity_event(
    payload: dict,
    request: Request,
    actor: CurrentActor = Depends(require_permissions("admin:*")),
    db: AsyncSession = Depends(get_db),
):
    event_type = str(payload.get("event_type") or "").strip()
    if not event_type:
        event_type = "ui.activity"
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    label = str(payload.get("label") or "").strip()
    event = BusinessEvent(
        business_id=actor.business.id,
        event_type=event_type,
        actor_user_id=actor.user.id,
        request_id=label or None,
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(event)
    await db.commit()
    return {"status": "accepted", "event_id": str(event.id), "details": details}


@router.get("/activity-timeline", response_model=list[dict])
async def get_activity_timeline(
    source: str = Query(default="all"),
    range_minutes: int = Query(default=1440, ge=1, le=10080),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("admin:*")),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=range_minutes)
    src = source.strip().lower()
    q = (search or "").strip().lower()

    def _match(text: str) -> bool:
        return (not q) or (q in text.lower())

    items: list[dict] = []

    if src in {"all", "backend", "audit"}:
        audit_rows = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.business_id == actor.business.id,
                    AuditLog.deleted_at.is_(None),
                    AuditLog.created_at >= since,
                ).order_by(AuditLog.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        for r in audit_rows:
            title = f"{r.action} ({r.status})"
            subtitle = f"{r.resource_type}:{r.resource_id or '-'} actor={r.actor_type}:{r.actor_id or '-'}"
            if _match(f"{title} {subtitle}"):
                items.append(
                    {
                        "source": "backend_audit",
                        "timestamp": r.created_at.isoformat(),
                        "title": title,
                        "subtitle": subtitle,
                        "id": str(r.id),
                    }
                )

    if src in {"all", "backend", "outbox"}:
        outbox_rows = (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.business_id == actor.business.id,
                    OutboxEvent.deleted_at.is_(None),
                    OutboxEvent.created_at >= since,
                ).order_by(OutboxEvent.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        for r in outbox_rows:
            title = f"{r.event_type} ({r.status})"
            subtitle = f"operation={r.operation_id or '-'} error={r.error_message or '-'}"
            if _match(f"{title} {subtitle}"):
                items.append(
                    {
                        "source": "backend_outbox",
                        "timestamp": r.created_at.isoformat(),
                        "title": title,
                        "subtitle": subtitle,
                        "id": str(r.id),
                    }
                )

    if src in {"all", "backend", "webhook"}:
        webhook_rows = (
            await db.execute(
                select(WebhookEvent).where(
                    WebhookEvent.business_id == actor.business.id,
                    WebhookEvent.deleted_at.is_(None),
                    WebhookEvent.created_at >= since,
                ).order_by(WebhookEvent.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        for r in webhook_rows:
            title = f"webhook:{r.provider} ({r.processing_status})"
            subtitle = f"event_id={r.event_id} status={r.status}"
            if _match(f"{title} {subtitle}"):
                items.append(
                    {
                        "source": "backend_webhook",
                        "timestamp": r.created_at.isoformat(),
                        "title": title,
                        "subtitle": subtitle,
                        "id": str(r.id),
                    }
                )

        provider_rows = (
            await db.execute(
                select(ProviderWebhookEvent).where(
                    ProviderWebhookEvent.business_id == actor.business.id,
                    ProviderWebhookEvent.deleted_at.is_(None),
                    ProviderWebhookEvent.created_at >= since,
                ).order_by(ProviderWebhookEvent.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        for r in provider_rows:
            title = f"provider_webhook:{r.provider} ({r.processing_status})"
            subtitle = f"event_id={r.event_id}"
            if _match(f"{title} {subtitle}"):
                items.append(
                    {
                        "source": "backend_provider_webhook",
                        "timestamp": r.created_at.isoformat(),
                        "title": title,
                        "subtitle": subtitle,
                        "id": str(r.id),
                    }
                )

    if src in {"all", "backend", "admin_access"}:
        access_rows = (
            await db.execute(
                select(AdminAccessAuditLog).where(
                    AdminAccessAuditLog.business_id == actor.business.id,
                    AdminAccessAuditLog.deleted_at.is_(None),
                    AdminAccessAuditLog.created_at >= since,
                ).order_by(AdminAccessAuditLog.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        for r in access_rows:
            title = f"admin_access:{r.action}"
            subtitle = f"entity={r.entity_type}:{r.entity_id or '-'} admin={r.admin_user_id}"
            if _match(f"{title} {subtitle}"):
                items.append(
                    {
                        "source": "backend_admin_access",
                        "timestamp": r.created_at.isoformat(),
                        "title": title,
                        "subtitle": subtitle,
                        "id": str(r.id),
                    }
                )

    if src in {"all", "ui"}:
        ui_rows = (
            await db.execute(
                select(BusinessEvent).where(
                    BusinessEvent.business_id == actor.business.id,
                    BusinessEvent.deleted_at.is_(None),
                    BusinessEvent.created_at >= since,
                    BusinessEvent.event_type.ilike("ui.%"),
                ).order_by(BusinessEvent.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        for r in ui_rows:
            title = r.event_type
            subtitle = f"label={r.request_id or '-'} user={r.actor_user_id or '-'}"
            if _match(f"{title} {subtitle}"):
                items.append(
                    {
                        "source": "ui",
                        "timestamp": r.created_at.isoformat(),
                        "title": title,
                        "subtitle": subtitle,
                        "id": str(r.id),
                    }
                )

    items.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return items[:limit]


@router.get("/audit-logs", response_model=list[dict])
async def list_audit_logs(
    action: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("admin:*")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).where(
        AuditLog.business_id == actor.business.id,
        AuditLog.deleted_at.is_(None),
    )
    if action:
        stmt = stmt.where(AuditLog.action == action.strip())
    if status:
        stmt = stmt.where(AuditLog.status == status.strip().lower())
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": str(r.id),
            "action": r.action,
            "status": r.status,
            "actor_type": r.actor_type,
            "actor_id": r.actor_id,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "operation_id": r.operation_id,
            "details": r.details or {},
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/access-grants", response_model=list[dict])
async def list_admin_access_grants(
    active_only: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("admin:*")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AdminAccessGrant).where(
        AdminAccessGrant.business_id == actor.business.id,
        AdminAccessGrant.deleted_at.is_(None),
    )
    if active_only:
        now = datetime.now(timezone.utc)
        stmt = stmt.where((AdminAccessGrant.expires_at.is_(None)) | (AdminAccessGrant.expires_at > now))
    rows = (await db.execute(stmt.order_by(AdminAccessGrant.created_at.desc(), AdminAccessGrant.id.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": str(r.id),
            "admin_user_id": str(r.admin_user_id),
            "approved_by": str(r.approved_by) if r.approved_by else None,
            "reason": r.reason,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/access-audit", response_model=list[dict])
async def list_admin_access_audit(
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("admin:*")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AdminAccessAuditLog).where(
        AdminAccessAuditLog.business_id == actor.business.id,
        AdminAccessAuditLog.deleted_at.is_(None),
    )
    if entity_type:
        stmt = stmt.where(AdminAccessAuditLog.entity_type == entity_type.strip())
    rows = (await db.execute(stmt.order_by(AdminAccessAuditLog.created_at.desc(), AdminAccessAuditLog.id.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": str(r.id),
            "admin_user_id": str(r.admin_user_id),
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "action": r.action,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/outbox-events", response_model=list[dict])
async def list_outbox_events(
    status: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    actor: CurrentActor = Depends(require_permissions("admin:*")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OutboxEvent).where(
        OutboxEvent.business_id == actor.business.id,
        OutboxEvent.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(OutboxEvent.status == status.strip().lower())
    if event_type:
        stmt = stmt.where(OutboxEvent.event_type == event_type.strip())
    rows = (await db.execute(stmt.order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": str(r.id),
            "operation_id": r.operation_id,
            "event_type": r.event_type,
            "status": r.status,
            "payload_json": r.payload_json or {},
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/system-health", response_model=dict)
async def get_system_health(
    actor: CurrentActor = Depends(require_permissions("admin:*")),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    pending_outbox = int(
        (
            await db.execute(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.business_id == actor.business.id,
                    OutboxEvent.deleted_at.is_(None),
                    OutboxEvent.status == "pending",
                )
            )
        ).scalar_one()
        or 0
    )
    failed_outbox = int(
        (
            await db.execute(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.business_id == actor.business.id,
                    OutboxEvent.deleted_at.is_(None),
                    OutboxEvent.status == "failed",
                )
            )
        ).scalar_one()
        or 0
    )
    webhook_failed_24h = int(
        (
            await db.execute(
                select(func.count(WebhookEvent.id)).where(
                    WebhookEvent.business_id == actor.business.id,
                    WebhookEvent.deleted_at.is_(None),
                    WebhookEvent.processing_status == "failed",
                    WebhookEvent.created_at >= last_24h,
                )
            )
        ).scalar_one()
        or 0
    )
    provider_webhook_failed_24h = int(
        (
            await db.execute(
                select(func.count(ProviderWebhookEvent.id)).where(
                    ProviderWebhookEvent.business_id == actor.business.id,
                    ProviderWebhookEvent.deleted_at.is_(None),
                    ProviderWebhookEvent.processing_status == "failed",
                    ProviderWebhookEvent.created_at >= last_24h,
                )
            )
        ).scalar_one()
        or 0
    )
    return {
        "pending_outbox_events": pending_outbox,
        "failed_outbox_events": failed_outbox,
        "webhook_failures_24h": webhook_failed_24h,
        "provider_webhook_failures_24h": provider_webhook_failed_24h,
        "health": "degraded" if (failed_outbox > 0 or webhook_failed_24h > 0 or provider_webhook_failed_24h > 0) else "healthy",
        "checked_at": now.isoformat(),
    }

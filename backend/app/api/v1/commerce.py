from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.core.exceptions import BadRequestException
from app.database import get_db
from app.models.business_domains import Campaign, CampaignRecipient, Contact

router = APIRouter(prefix="/commerce", tags=["Commerce"])


def _as_float(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return fallback


@router.get("/summary", response_model=dict)
async def get_commerce_summary(
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    contacts = (
        await db.execute(
            select(Contact).where(
                Contact.business_id == actor.business.id,
                Contact.deleted_at.is_(None),
            ).limit(5000)
        )
    ).scalars().all()
    total_orders = 0
    total_cart_events = 0
    total_revenue = 0.0
    purchasing_contacts = 0
    for c in contacts:
        attrs = c.custom_attributes or {}
        orders = attrs.get("orders") if isinstance(attrs, dict) else None
        carts = attrs.get("cart_events") if isinstance(attrs, dict) else None
        spent = attrs.get("total_spent") if isinstance(attrs, dict) else None
        if isinstance(orders, list):
            total_orders += len(orders)
            if len(orders) > 0:
                purchasing_contacts += 1
        if isinstance(carts, list):
            total_cart_events += len(carts)
        total_revenue += _as_float(spent, 0.0)

    campaign_rows = (
        await db.execute(
            select(Campaign).where(
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    campaign_spend = sum(_as_float(r.actual_cost, 0.0) for r in campaign_rows)
    roi = ((total_revenue - campaign_spend) / campaign_spend) if campaign_spend > 0 else None
    conversion_rate = (purchasing_contacts / len(contacts)) if contacts else 0.0

    return {
        "contacts_with_orders": purchasing_contacts,
        "total_orders": total_orders,
        "total_cart_events": total_cart_events,
        "total_revenue": round(total_revenue, 2),
        "campaign_spend": round(campaign_spend, 2),
        "roi": round(roi, 4) if roi is not None else None,
        "contact_conversion_rate": round(conversion_rate, 4),
    }


@router.get("/orders", response_model=list[dict])
async def list_commerce_orders(
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    contacts = (
        await db.execute(
            select(Contact).where(
                Contact.business_id == actor.business.id,
                Contact.deleted_at.is_(None),
            ).limit(5000)
        )
    ).scalars().all()
    rows: list[dict] = []
    for c in contacts:
        attrs = c.custom_attributes or {}
        orders = attrs.get("orders") if isinstance(attrs, dict) else None
        if not isinstance(orders, list):
            continue
        for order in orders:
            if not isinstance(order, dict):
                continue
            rows.append(
                {
                    "contact_id": str(c.id),
                    "contact_name": c.display_name,
                    "order_id": str(order.get("order_id") or order.get("id") or ""),
                    "status": str(order.get("status") or "unknown"),
                    "currency": str(order.get("currency") or "USD"),
                    "amount": _as_float(order.get("amount") or order.get("total") or 0.0),
                    "created_at": order.get("created_at"),
                    "raw": order,
                }
            )
    rows.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return rows[:limit]


@router.get("/carts", response_model=list[dict])
async def list_commerce_carts(
    limit: int = Query(default=200, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    contacts = (
        await db.execute(
            select(Contact).where(
                Contact.business_id == actor.business.id,
                Contact.deleted_at.is_(None),
            ).limit(5000)
        )
    ).scalars().all()
    rows: list[dict] = []
    for c in contacts:
        attrs = c.custom_attributes or {}
        carts = attrs.get("cart_events") if isinstance(attrs, dict) else None
        if not isinstance(carts, list):
            continue
        for evt in carts:
            if not isinstance(evt, dict):
                continue
            rows.append(
                {
                    "contact_id": str(c.id),
                    "contact_name": c.display_name,
                    "cart_id": str(evt.get("cart_id") or evt.get("id") or ""),
                    "event_type": str(evt.get("event_type") or evt.get("type") or "unknown"),
                    "value": _as_float(evt.get("value") or evt.get("amount") or 0.0),
                    "occurred_at": evt.get("occurred_at") or evt.get("created_at"),
                    "raw": evt,
                }
            )
    rows.sort(key=lambda x: str(x.get("occurred_at") or ""), reverse=True)
    return rows[:limit]


@router.get("/conversions", response_model=dict)
async def get_conversion_metrics(
    campaign_id: str | None = Query(default=None),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CampaignRecipient).where(
        CampaignRecipient.business_id == actor.business.id,
        CampaignRecipient.deleted_at.is_(None),
    )
    if campaign_id:
        try:
            campaign_uuid = UUID(campaign_id)
        except ValueError as exc:
            raise BadRequestException("Invalid campaign_id") from exc
        stmt = stmt.where(CampaignRecipient.campaign_id == campaign_uuid)
    rows = (await db.execute(stmt)).scalars().all()
    sent = sum(1 for r in rows if str(r.status or "").lower() in {"sent", "delivered", "read", "replied"})
    delivered = sum(1 for r in rows if str(r.status or "").lower() in {"delivered", "read", "replied"})
    replied = sum(1 for r in rows if str(r.status or "").lower() == "replied")
    failed = sum(1 for r in rows if str(r.status or "").lower() == "failed")
    reserved = sum(1 for r in rows if str(r.status or "").lower() in {"pending", "queued", "reserved"})

    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "as_of_date": today,
        "campaign_id": campaign_id,
        "sent": sent,
        "delivered": delivered,
        "replied": replied,
        "failed": failed,
        "reserved": reserved,
        "delivery_rate": round((delivered / sent), 4) if sent > 0 else 0.0,
        "reply_rate": round((replied / delivered), 4) if delivered > 0 else 0.0,
        "failure_rate": round((failed / max(1, len(rows))), 4),
    }


@router.get("/campaign-attribution", response_model=list[dict])
async def commerce_campaign_attribution(
    limit: int = Query(default=100, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Campaign).where(
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            ).order_by(Campaign.created_at.desc(), Campaign.id.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "campaign_id": str(r.id),
            "campaign_name": r.name,
            "template_category": r.template_category,
            "recipients": int(r.total_recipients or 0),
            "delivered": int(r.delivered_count or 0),
            "replied": int(r.replied_count or 0),
            "actual_cost": _as_float(r.actual_cost, 0.0),
            "estimated_cost": _as_float(r.estimated_cost, 0.0),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

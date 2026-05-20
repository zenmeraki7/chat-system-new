from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.core.exceptions import BadRequestException
from app.database import get_db
from app.models.business_domains import Campaign, CampaignRecipient, MessageMetricsDaily
from app.models.message import Message, MessageDirection

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _as_float(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return fallback


@router.get("/overview", response_model=dict)
async def analytics_overview(
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    campaigns = (
        await db.execute(
            select(Campaign).where(
                Campaign.business_id == actor.business.id,
                Campaign.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    recipients_total = sum(int(c.total_recipients or 0) for c in campaigns)
    delivered_total = sum(int(c.delivered_count or 0) for c in campaigns)
    replied_total = sum(int(c.replied_count or 0) for c in campaigns)
    failed_total = sum(int(c.failed_count or 0) for c in campaigns)
    spend_total = sum(_as_float(c.actual_cost, 0.0) for c in campaigns)
    return {
        "campaign_count": len(campaigns),
        "recipient_count": recipients_total,
        "delivered_count": delivered_total,
        "replied_count": replied_total,
        "failed_count": failed_total,
        "delivery_rate": round((delivered_total / recipients_total), 4) if recipients_total > 0 else 0.0,
        "reply_rate": round((replied_total / delivered_total), 4) if delivered_total > 0 else 0.0,
        "total_spend": round(spend_total, 2),
    }


@router.get("/funnel", response_model=dict)
async def analytics_funnel(
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
            from uuid import UUID
            campaign_uuid = UUID(campaign_id)
        except ValueError as exc:
            raise BadRequestException("Invalid campaign_id") from exc
        stmt = stmt.where(CampaignRecipient.campaign_id == campaign_uuid)
    rows = (await db.execute(stmt)).scalars().all()
    counts = {
        "pending": 0,
        "queued": 0,
        "reserved": 0,
        "sending": 0,
        "sent": 0,
        "delivered": 0,
        "read": 0,
        "replied": 0,
        "failed": 0,
    }
    for r in rows:
        key = str(r.status or "").lower()
        if key in counts:
            counts[key] += 1
    total = len(rows)
    return {
        "total_recipients": total,
        "funnel": counts,
        "completion_rate": round((counts["delivered"] + counts["read"] + counts["replied"]) / total, 4) if total > 0 else 0.0,
        "failure_rate": round(counts["failed"] / total, 4) if total > 0 else 0.0,
    }


@router.get("/campaigns", response_model=list[dict])
async def analytics_by_campaign(
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
            "name": r.name,
            "status": r.status,
            "type": r.type,
            "template_category": r.template_category,
            "total_recipients": int(r.total_recipients or 0),
            "delivered_count": int(r.delivered_count or 0),
            "read_count": int(r.read_count or 0),
            "replied_count": int(r.replied_count or 0),
            "failed_count": int(r.failed_count or 0),
            "actual_cost": _as_float(r.actual_cost, 0.0),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/messages/daily", response_model=list[dict])
async def analytics_messages_daily(
    days: int = Query(default=14, ge=1, le=90),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(MessageMetricsDaily).where(
                MessageMetricsDaily.business_id == actor.business.id,
                MessageMetricsDaily.deleted_at.is_(None),
                MessageMetricsDaily.date_bucket >= since,
            ).order_by(MessageMetricsDaily.date_bucket.asc(), MessageMetricsDaily.id.asc())
        )
    ).scalars().all()
    return [
        {
            "date_bucket": r.date_bucket.isoformat(),
            "phone_number_id": r.phone_number_id,
            "metric_key": r.metric_key,
            "dimension_key": r.dimension_key,
            "sent_count": int(r.sent_count or 0),
            "delivered_count": int(r.delivered_count or 0),
            "failed_count": int(r.failed_count or 0),
        }
        for r in rows
    ]


@router.get("/messages/summary", response_model=dict)
async def analytics_message_summary(
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    total_messages = int(
        (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.business_id == actor.business.id,
                    Message.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        or 0
    )
    outbound_messages = int(
        (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.business_id == actor.business.id,
                    Message.deleted_at.is_(None),
                    Message.direction == MessageDirection.OUTBOUND,
                )
            )
        ).scalar_one()
        or 0
    )
    inbound_messages = int(
        (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.business_id == actor.business.id,
                    Message.deleted_at.is_(None),
                    Message.direction == MessageDirection.INBOUND,
                )
            )
        ).scalar_one()
        or 0
    )
    return {
        "total_messages": total_messages,
        "outbound_messages": outbound_messages,
        "inbound_messages": inbound_messages,
        "inbound_outbound_ratio": round(inbound_messages / outbound_messages, 4) if outbound_messages > 0 else None,
    }

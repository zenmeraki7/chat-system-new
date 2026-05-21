import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.database import get_db
from app.models.business import Business
from app.models.business_domains import (
    Campaign,
    CampaignRecipient,
    Contact,
    ConversationStatusEvent,
    MessageStatusEvent,
    WebhookEvent,
)

router = APIRouter(prefix="/realtime", tags=["Realtime"])


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get("/events")
async def stream_realtime_events(
    campaign_id: str | None = Query(default=None),
    interval_ms: int = Query(default=3000, ge=1000, le=15000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    business_id = actor.business.id
    campaign_uuid = None
    if campaign_id:
        try:
            campaign_uuid = UUID(campaign_id)
        except ValueError:
            campaign_uuid = None

    async def event_generator():
        yield _sse("connected", {"business_id": str(business_id), "ts": datetime.now(timezone.utc).isoformat()})

        last_message_status_ts = None
        last_conversation_update_ts = None
        last_campaign_update_ts = None
        last_wallet_ts = None
        last_webhook_ts = None
        last_assignment_ts = None

        while True:
            now = datetime.now(timezone.utc)

            # New incoming messages / message status updates
            msg_stmt = select(MessageStatusEvent).where(
                MessageStatusEvent.business_id == business_id,
                MessageStatusEvent.deleted_at.is_(None),
            )
            if last_message_status_ts is not None:
                msg_stmt = msg_stmt.where(MessageStatusEvent.created_at > last_message_status_ts)
            msg_rows = (await db.execute(msg_stmt.order_by(MessageStatusEvent.created_at.asc()).limit(200))).scalars().all()
            for row in msg_rows:
                payload = {
                    "id": str(row.id),
                    "message_id": str(row.message_id),
                    "status": row.status,
                    "provider_message_id": row.provider_message_id,
                    "created_at": row.created_at.isoformat(),
                }
                yield _sse("message_status", payload)
                if row.created_at and (last_message_status_ts is None or row.created_at > last_message_status_ts):
                    last_message_status_ts = row.created_at

            # Campaign progress updates
            camp_stmt = select(Campaign).where(
                Campaign.business_id == business_id,
                Campaign.deleted_at.is_(None),
            )
            if campaign_uuid:
                camp_stmt = camp_stmt.where(Campaign.id == campaign_uuid)
            if last_campaign_update_ts is not None:
                camp_stmt = camp_stmt.where(Campaign.updated_at > last_campaign_update_ts)
            camp_rows = (await db.execute(camp_stmt.order_by(Campaign.updated_at.asc()).limit(100))).scalars().all()
            for row in camp_rows:
                payload = {
                    "campaign_id": str(row.id),
                    "status": row.status,
                    "total_recipients": int(row.total_recipients or 0),
                    "delivered_count": int(row.delivered_count or 0),
                    "failed_count": int(row.failed_count or 0),
                    "read_count": int(row.read_count or 0),
                    "replied_count": int(row.replied_count or 0),
                    "actual_cost": float(row.actual_cost or 0.0),
                    "updated_at": row.updated_at.isoformat(),
                }
                yield _sse("campaign_progress", payload)
                if row.updated_at and (last_campaign_update_ts is None or row.updated_at > last_campaign_update_ts):
                    last_campaign_update_ts = row.updated_at

            # Wallet balance proxy from business billing status updates
            biz_stmt = select(Business).where(Business.id == business_id)
            if last_wallet_ts is not None:
                biz_stmt = biz_stmt.where(Business.updated_at > last_wallet_ts)
            biz_row = (await db.execute(biz_stmt)).scalar_one_or_none()
            if biz_row is not None:
                payload = {
                    "business_id": str(biz_row.id),
                    "billing_status": biz_row.billing_status,
                    "updated_at": biz_row.updated_at.isoformat(),
                }
                yield _sse("wallet_balance", payload)
                if biz_row.updated_at and (last_wallet_ts is None or biz_row.updated_at > last_wallet_ts):
                    last_wallet_ts = biz_row.updated_at

            # Agent assignment + conversation updates
            conv_stmt = select(ConversationStatusEvent).where(
                ConversationStatusEvent.business_id == business_id,
                ConversationStatusEvent.deleted_at.is_(None),
            )
            if last_conversation_update_ts is not None:
                conv_stmt = conv_stmt.where(ConversationStatusEvent.created_at > last_conversation_update_ts)
            conv_rows = (await db.execute(conv_stmt.order_by(ConversationStatusEvent.created_at.asc()).limit(200))).scalars().all()
            for row in conv_rows:
                payload = {
                    "id": str(row.id),
                    "conversation_id": str(row.conversation_id),
                    "old_status": row.old_status,
                    "new_status": row.new_status,
                    "reason": row.reason,
                    "created_at": row.created_at.isoformat(),
                }
                yield _sse("conversation_update", payload)
                if row.reason and "assign" in str(row.reason).lower():
                    yield _sse("agent_assignment", payload)
                    if last_assignment_ts is None or row.created_at > last_assignment_ts:
                        last_assignment_ts = row.created_at
                if row.created_at and (last_conversation_update_ts is None or row.created_at > last_conversation_update_ts):
                    last_conversation_update_ts = row.created_at

            # Webhook health alerts
            wh_stmt = select(WebhookEvent).where(
                WebhookEvent.business_id == business_id,
                WebhookEvent.deleted_at.is_(None),
            )
            if last_webhook_ts is not None:
                wh_stmt = wh_stmt.where(WebhookEvent.created_at > last_webhook_ts)
            wh_rows = (await db.execute(wh_stmt.order_by(WebhookEvent.created_at.asc()).limit(200))).scalars().all()
            for row in wh_rows:
                status = str(row.processing_status or "unknown")
                payload = {
                    "id": str(row.id),
                    "provider": row.provider,
                    "processing_status": status,
                    "status": row.status,
                    "received_at": row.received_at.isoformat() if row.received_at else None,
                    "created_at": row.created_at.isoformat(),
                }
                if status.lower() == "failed":
                    yield _sse("webhook_health_alert", payload)
                else:
                    yield _sse("webhook_update", payload)
                if row.created_at and (last_webhook_ts is None or row.created_at > last_webhook_ts):
                    last_webhook_ts = row.created_at

            # heartbeat to keep connection alive
            yield _sse("heartbeat", {"ts": now.isoformat()})
            await asyncio.sleep(interval_ms / 1000.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/table-patches")
async def stream_table_patches(
    table: str = Query(default="inbox"),
    interval_ms: int = Query(default=2500, ge=1000, le=15000),
    actor: CurrentActor = Depends(require_permissions("campaigns:read")),
    db: AsyncSession = Depends(get_db),
):
    business_id = actor.business.id
    normalized = str(table or "").strip().lower()
    if normalized not in {"inbox", "campaigns", "contacts"}:
        normalized = "inbox"

    async def generator():
        yield _sse("connected", {"table": normalized, "business_id": str(business_id), "ts": datetime.now(timezone.utc).isoformat()})
        last_ts = None
        while True:
            if normalized == "contacts":
                stmt = select(Contact).where(Contact.business_id == business_id, Contact.deleted_at.is_(None))
                if last_ts is not None:
                    stmt = stmt.where(Contact.updated_at > last_ts)
                rows = (await db.execute(stmt.order_by(Contact.updated_at.asc()).limit(200))).scalars().all()
                for row in rows:
                    payload = {
                        "row_id": str(row.id),
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                        "opt_in_status": row.opt_in_status,
                        "blocked": bool(row.blocked_at),
                        "unsubscribed": bool(row.unsubscribed_at),
                    }
                    yield _sse("row_patch", payload)
                    if row.updated_at and (last_ts is None or row.updated_at > last_ts):
                        last_ts = row.updated_at
            elif normalized == "campaigns":
                stmt = select(Campaign).where(Campaign.business_id == business_id, Campaign.deleted_at.is_(None))
                if last_ts is not None:
                    stmt = stmt.where(Campaign.updated_at > last_ts)
                rows = (await db.execute(stmt.order_by(Campaign.updated_at.asc()).limit(200))).scalars().all()
                for row in rows:
                    payload = {
                        "row_id": str(row.id),
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                        "status": row.status,
                        "delivered_count": int(row.delivered_count or 0),
                        "failed_count": int(row.failed_count or 0),
                        "read_count": int(row.read_count or 0),
                        "replied_count": int(row.replied_count or 0),
                    }
                    yield _sse("row_patch", payload)
                    if row.updated_at and (last_ts is None or row.updated_at > last_ts):
                        last_ts = row.updated_at
            else:
                stmt = select(ConversationStatusEvent).where(
                    ConversationStatusEvent.business_id == business_id,
                    ConversationStatusEvent.deleted_at.is_(None),
                )
                if last_ts is not None:
                    stmt = stmt.where(ConversationStatusEvent.created_at > last_ts)
                rows = (await db.execute(stmt.order_by(ConversationStatusEvent.created_at.asc()).limit(200))).scalars().all()
                for row in rows:
                    payload = {
                        "row_id": str(row.conversation_id),
                        "updated_at": row.created_at.isoformat() if row.created_at else None,
                        "status": row.new_status,
                        "reason": row.reason,
                    }
                    yield _sse("row_patch", payload)
                    if row.created_at and (last_ts is None or row.created_at > last_ts):
                        last_ts = row.created_at
            yield _sse("heartbeat", {"table": normalized, "ts": datetime.now(timezone.utc).isoformat()})
            await asyncio.sleep(interval_ms / 1000.0)

    return StreamingResponse(generator(), media_type="text/event-stream")

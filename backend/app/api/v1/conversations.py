from typing import List
from datetime import datetime, timezone, timedelta
from uuid import UUID
import base64
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.conversation import (
    AssignConversationRequest,
    AddConversationTagRequest,
    AddInternalNoteRequest,
    InboxSavedViewRequest,
    TypingPresenceRequest,
    CloseConversationRequest,
    ConversationDetailResponse,
    ConversationInboxItemResponse,
    ConversationProfileUpdate,
    ReopenConversationRequest,
    SlaPolicyUpsertRequest,
    ApplySlaRequest,
    ConversationTimelineItem,
    WorkloadRoutingRequest,
    WorkloadRoutingDecisionResponse,
)
from app.schemas.message import AgentMessageResponse
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_repo import MessageRepository
from app.api.deps import CurrentActor, require_permissions
from app.core.exceptions import NotFoundException, ForbiddenException
from app.services.conversation_service import ConversationService
from app.models.business_domains import (
    ConversationTag,
    InternalNote,
    InternalNoteMention,
    ConversationSavedView,
    ConversationTypingPresence,
    ConversationAssignment,
    ConversationStatusEvent,
    ConversationEvent,
)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _encode_conversation_cursor(last_message_at: datetime, conversation_id: UUID) -> str:
    # Cursor format: "<iso8601>|<uuid>" encoded as URL-safe base64.
    raw = f"{last_message_at.astimezone(timezone.utc).isoformat()}|{conversation_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_conversation_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        ts_raw, id_raw = decoded.split("|", 1)
        ts = datetime.fromisoformat(ts_raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (ts.astimezone(timezone.utc), UUID(id_raw))
    except Exception:
        return None


@router.get("", response_model=dict)
async def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    assigned_user_id: UUID | None = Query(default=None),
    priority: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    search: str | None = Query(default=None),
    actor: CurrentActor = Depends(require_permissions("conversations:read")),
    db: AsyncSession = Depends(get_db),
):
    cursor_last_message_at: datetime | None = None
    cursor_id: UUID | None = None
    if cursor:
        parsed_cursor = _decode_conversation_cursor(cursor)
        if parsed_cursor is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        cursor_last_message_at, cursor_id = parsed_cursor

    repo = ConversationRepository(db)
    fetch_limit = max(1, min(limit, 100)) + 1
    conversations = await repo.list_for_business(
        business_id=actor.business.id,
        limit=fetch_limit,
        cursor_last_message_at=cursor_last_message_at,
        cursor_id=cursor_id,
        status=status,
        assigned_user_id=assigned_user_id,
        priority=priority,
        tag=tag,
        search=search,
    )

    page_rows = conversations[:limit]
    has_more = len(conversations) > limit
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        if last.last_message_at is not None:
            next_cursor = _encode_conversation_cursor(last.last_message_at, last.id)

    msg_repo = MessageRepository(db)
    result = []
    for conv in page_rows:
        count = await msg_repo.count_by_conversation(actor.business.id, conv.id)
        tag_rows = await db.execute(
            select(ConversationTag.tag).where(
                ConversationTag.conversation_id == conv.id,
                ConversationTag.deleted_at.is_(None),
            )
        )
        result.append(
            ConversationInboxItemResponse(
                public_id=conv.id,
                status=conv.status,
                visitor_name=conv.visitor_name,
                last_message_at=conv.last_message_at,
                unread_count=count,
                assigned_user_id=conv.assigned_user_id,
                assigned_team_id=conv.assigned_team_id,
                channel_id=conv.channel_id,
                priority=conv.priority,
                tags=[row[0] for row in tag_rows.all()],
                first_response_due_at=conv.first_response_due_at,
                resolution_due_at=conv.resolution_due_at,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
            )
        )
    return {"items": [row.model_dump() for row in result], "next_cursor": next_cursor}


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    actor: CurrentActor = Depends(require_permissions("conversations:read")),
    db: AsyncSession = Depends(get_db),
):
    repo = ConversationRepository(db)
    conv = await repo.get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")
    if conv.business_id != actor.business.id:
        raise ForbiddenException()
    count = await MessageRepository(db).count_by_conversation(actor.business.id, conv.id)
    return ConversationDetailResponse(
        public_id=conv.id,
        status=conv.status,
        visitor_name=conv.visitor_name,
        visitor_email=conv.visitor_email,
        message_count=count,
        assigned_user_id=conv.assigned_user_id,
        assigned_team_id=conv.assigned_team_id,
        channel_id=conv.channel_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get("/{conversation_id}/messages", response_model=dict)
async def get_messages(
    conversation_id: str,
    search: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="asc"),
    limit: int = Query(default=100, ge=1, le=1000),
    actor: CurrentActor = Depends(require_permissions("conversations:read")),
    db: AsyncSession = Depends(get_db),
):
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")
    if conv.business_id != actor.business.id:
        raise ForbiddenException()

    from app.models.message import Message
    stmt = select(Message).where(
        Message.business_id == actor.business.id,
        Message.conversation_id == UUID(conversation_id),
        Message.deleted_at.is_(None),
    )
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(or_(Message.content_text.ilike(q), Message.content.ilike(q), Message.message_kind.ilike(q)))
    sort_key = Message.created_at if sort_by == "created_at" else Message.updated_at
    sort_desc = str(sort_dir).lower() != "asc"
    if cursor:
        cursor_row = (
            await db.execute(
                select(Message.id, sort_key).where(
                    Message.id == UUID(cursor),
                    Message.business_id == actor.business.id,
                    Message.conversation_id == UUID(conversation_id),
                    Message.deleted_at.is_(None),
                )
            )
        ).first()
        if cursor_row is not None:
            cursor_id, cursor_val = cursor_row
            if cursor_val is not None:
                if sort_desc:
                    stmt = stmt.where(or_(sort_key < cursor_val, and_(sort_key == cursor_val, Message.id < cursor_id)))
                else:
                    stmt = stmt.where(or_(sort_key > cursor_val, and_(sort_key == cursor_val, Message.id > cursor_id)))
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    order_primary = sort_key.desc() if sort_desc else sort_key.asc()
    order_secondary = Message.id.desc() if sort_desc else Message.id.asc()
    messages = (await db.execute(stmt.order_by(order_primary, order_secondary).limit(limit + 1))).scalars().all()
    page_rows = messages[:limit]
    next_cursor = str(page_rows[-1].id) if len(messages) > limit and page_rows else None
    items = [
        AgentMessageResponse(
            public_id=message.id,
            conversation_public_id=message.conversation_id,
            direction=message.direction,
            sender_type=message.sender_type,
            message_type=message.message_kind,
            content_text=message.content_text or message.content,
            status=message.status,
            created_at=message.created_at,
            is_redacted=bool(message.redacted_at or message.content_redacted_at),
            delivered_at=message.delivered_at,
            read_at=message.read_at,
            failed_at=message.failed_at,
            attachments=[],
        )
        for message in page_rows
    ]
    return {"items": [row.model_dump() for row in items], "next_cursor": next_cursor, "total": total}


@router.patch("/{conversation_id}/profile", response_model=ConversationDetailResponse)
async def update_conversation_profile(
    conversation_id: str,
    payload: ConversationProfileUpdate,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    repo = ConversationRepository(db)
    conv = await repo.get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")
    if conv.archived_at is not None and (
        payload.visitor_name is not None or payload.visitor_email is not None
    ):
        raise ForbiddenException("Archived conversations must be unarchived before mutable updates")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        conv = await repo.update_for_business(
            business_id=actor.business.id,
            id=UUID(conversation_id),
            values=updates,
        )
    count = await MessageRepository(db).count_by_conversation(actor.business.id, conv.id)
    return ConversationDetailResponse(
        public_id=conv.id,
        status=conv.status,
        visitor_name=conv.visitor_name,
        visitor_email=conv.visitor_email,
        message_count=count,
        assigned_user_id=conv.assigned_user_id,
        assigned_team_id=conv.assigned_team_id,
        channel_id=conv.channel_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.post("/{conversation_id}/close", response_model=ConversationDetailResponse)
async def close_conversation(
    conversation_id: str,
    payload: CloseConversationRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    del payload
    svc = ConversationService(db)
    conv = await svc.close(actor.business.id, UUID(conversation_id), actor.user.id)
    count = await MessageRepository(db).count_by_conversation(actor.business.id, conv.id)
    return ConversationDetailResponse(
        public_id=conv.id,
        status=conv.status,
        visitor_name=conv.visitor_name,
        visitor_email=conv.visitor_email,
        message_count=count,
        assigned_user_id=conv.assigned_user_id,
        assigned_team_id=conv.assigned_team_id,
        channel_id=conv.channel_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.post("/{conversation_id}/reopen", response_model=ConversationDetailResponse)
async def reopen_conversation(
    conversation_id: str,
    payload: ReopenConversationRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    del payload
    svc = ConversationService(db)
    conv = await svc.reopen(actor.business.id, UUID(conversation_id), actor.user.id)
    count = await MessageRepository(db).count_by_conversation(actor.business.id, conv.id)
    return ConversationDetailResponse(
        public_id=conv.id,
        status=conv.status,
        visitor_name=conv.visitor_name,
        visitor_email=conv.visitor_email,
        message_count=count,
        assigned_user_id=conv.assigned_user_id,
        assigned_team_id=conv.assigned_team_id,
        channel_id=conv.channel_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.post("/{conversation_id}/assign", response_model=ConversationDetailResponse)
async def assign_conversation(
    conversation_id: str,
    payload: AssignConversationRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    if payload.assigned_user_id is None and payload.assigned_team_id is None:
        raise HTTPException(status_code=400, detail="assigned_user_id or assigned_team_id is required")
    svc = ConversationService(db)
    conv = await svc.assign(
        business_id=actor.business.id,
        conversation_id=UUID(conversation_id),
        actor_user_id=actor.user.id,
        assigned_user_id=payload.assigned_user_id,
        assigned_team_id=payload.assigned_team_id,
    )
    count = await MessageRepository(db).count_by_conversation(actor.business.id, conv.id)
    return ConversationDetailResponse(
        public_id=conv.id,
        status=conv.status,
        visitor_name=conv.visitor_name,
        visitor_email=conv.visitor_email,
        message_count=count,
        assigned_user_id=conv.assigned_user_id,
        assigned_team_id=conv.assigned_team_id,
        channel_id=conv.channel_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.post("/sla-policies", response_model=dict)
async def upsert_sla_policy(
    payload: SlaPolicyUpsertRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    policy = await svc.upsert_sla_policy(
        business_id=actor.business.id,
        name=payload.name.strip(),
        response_minutes=payload.response_minutes,
        resolution_minutes=payload.resolution_minutes,
        actor_user_id=actor.user.id,
    )
    return {
        "id": str(policy.id),
        "name": policy.name,
        "response_minutes": policy.response_minutes,
        "resolution_minutes": policy.resolution_minutes,
    }


@router.post("/{conversation_id}/sla/apply", response_model=ConversationDetailResponse)
async def apply_sla_policy(
    conversation_id: str,
    payload: ApplySlaRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    conv = await svc.apply_sla_policy(
        business_id=actor.business.id,
        conversation_id=UUID(conversation_id),
        actor_user_id=actor.user.id,
        policy_name=payload.policy_name,
    )
    count = await MessageRepository(db).count_by_conversation(actor.business.id, conv.id)
    return ConversationDetailResponse(
        public_id=conv.id,
        status=conv.status,
        visitor_name=conv.visitor_name,
        visitor_email=conv.visitor_email,
        message_count=count,
        assigned_user_id=conv.assigned_user_id,
        assigned_team_id=conv.assigned_team_id,
        channel_id=conv.channel_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get("/{conversation_id}/timeline", response_model=list[ConversationTimelineItem])
async def get_conversation_timeline(
    conversation_id: str,
    actor: CurrentActor = Depends(require_permissions("conversations:read")),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationRepository(db).get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")

    events: list[ConversationTimelineItem] = []
    assignment_rows = await db.execute(
        select(ConversationAssignment).where(
            ConversationAssignment.conversation_id == conv.id,
            ConversationAssignment.deleted_at.is_(None),
        )
    )
    for row in assignment_rows.scalars().all():
        events.append(
            ConversationTimelineItem(
                event_type="conversation.assigned",
                created_at=row.created_at,
                payload={
                    "assigned_user_id": str(row.assigned_user_id) if row.assigned_user_id else None,
                    "assigned_team_id": str(row.assigned_team_id) if row.assigned_team_id else None,
                    "status": row.status,
                },
            )
        )

    status_rows = await db.execute(
        select(ConversationStatusEvent).where(
            ConversationStatusEvent.conversation_id == conv.id,
            ConversationStatusEvent.deleted_at.is_(None),
        )
    )
    for row in status_rows.scalars().all():
        events.append(
            ConversationTimelineItem(
                event_type="conversation.status.changed",
                created_at=row.created_at,
                payload={
                    "old_status": row.old_status,
                    "new_status": row.new_status,
                    "changed_by_user_id": str(row.changed_by_user_id) if row.changed_by_user_id else None,
                },
            )
        )

    generic_rows = await db.execute(
        select(ConversationEvent).where(
            ConversationEvent.conversation_id == conv.id,
            ConversationEvent.deleted_at.is_(None),
        )
    )
    for row in generic_rows.scalars().all():
        events.append(
            ConversationTimelineItem(
                event_type=row.event_type,
                created_at=row.created_at,
                payload=row.payload_json or {},
            )
        )

    note_rows = await db.execute(
        select(InternalNote).where(
            InternalNote.conversation_id == conv.id,
            InternalNote.deleted_at.is_(None),
        )
    )
    for row in note_rows.scalars().all():
        events.append(
            ConversationTimelineItem(
                event_type="conversation.internal_note.added",
                created_at=row.created_at,
                payload={
                    "internal_note_id": str(row.id),
                    "author_user_id": str(row.author_user_id) if row.author_user_id else None,
                    "note": row.note,
                },
            )
        )

    events.sort(key=lambda item: item.created_at)
    return events


@router.post("/{conversation_id}/route-assignment", response_model=WorkloadRoutingDecisionResponse)
async def route_assignment(
    conversation_id: str,
    payload: WorkloadRoutingRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    conv, open_load = await svc.auto_route_assignment(
        business_id=actor.business.id,
        conversation_id=UUID(conversation_id),
        actor_user_id=actor.user.id,
        strategy=payload.strategy,
        team_id=payload.team_id,
        eligible_user_ids=payload.eligible_user_ids,
        max_capacity_per_agent=payload.max_capacity_per_agent,
    )
    return WorkloadRoutingDecisionResponse(
        assigned_user_id=conv.assigned_user_id,
        assigned_team_id=conv.assigned_team_id,
        strategy=payload.strategy,
        open_load_for_assigned_user=open_load,
    )


@router.post("/{conversation_id}/tags", response_model=dict)
async def add_conversation_tag(
    conversation_id: str,
    payload: AddConversationTagRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationRepository(db).get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")
    db.add(ConversationTag(conversation_id=conv.id, tag=payload.tag.strip().lower()))
    await db.commit()
    return {"status": "ok"}


@router.post("/{conversation_id}/internal-notes", response_model=dict)
async def add_internal_note(
    conversation_id: str,
    payload: AddInternalNoteRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationRepository(db).get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")
    note = InternalNote(conversation_id=conv.id, author_user_id=actor.user.id, note=payload.note.strip())
    db.add(note)
    await db.flush()
    for uid in payload.mentioned_user_ids:
        db.add(InternalNoteMention(internal_note_id=note.id, mentioned_user_id=uid))
    await db.commit()
    return {"status": "ok", "internal_note_id": str(note.id)}


@router.post("/saved-views", response_model=dict)
async def create_saved_view(
    payload: InboxSavedViewRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    row = ConversationSavedView(
        business_id=actor.business.id,
        owner_user_id=actor.user.id,
        name=payload.name.strip(),
        filters_json=payload.filters_json,
        visibility=payload.visibility,
    )
    db.add(row)
    await db.commit()
    return {"status": "ok", "saved_view_id": str(row.id)}


@router.get("/saved-views", response_model=list[dict])
async def list_saved_views(
    actor: CurrentActor = Depends(require_permissions("conversations:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(ConversationSavedView).where(
            ConversationSavedView.business_id == actor.business.id,
            ConversationSavedView.deleted_at.is_(None),
        )
    )
    return [
        {"id": str(r.id), "name": r.name, "filters_json": r.filters_json, "visibility": r.visibility}
        for r in rows.scalars().all()
    ]


@router.post("/{conversation_id}/typing-presence", response_model=dict)
async def update_typing_presence(
    conversation_id: str,
    payload: TypingPresenceRequest,
    actor: CurrentActor = Depends(require_permissions("conversations:write")),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationRepository(db).get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")
    await db.execute(
        delete(ConversationTypingPresence).where(
            ConversationTypingPresence.conversation_id == conv.id,
            ConversationTypingPresence.user_id == actor.user.id,
        )
    )
    db.add(
        ConversationTypingPresence(
            conversation_id=conv.id,
            business_id=actor.business.id,
            user_id=actor.user.id,
            status=payload.status,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=payload.ttl_seconds),
        )
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/{conversation_id}/typing-presence", response_model=list[dict])
async def get_typing_presence(
    conversation_id: str,
    actor: CurrentActor = Depends(require_permissions("conversations:read")),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationRepository(db).get_for_business(actor.business.id, UUID(conversation_id))
    if not conv:
        raise NotFoundException("Conversation not found")
    rows = await db.execute(
        select(ConversationTypingPresence).where(
            ConversationTypingPresence.conversation_id == conv.id,
            ConversationTypingPresence.expires_at > datetime.now(timezone.utc),
            ConversationTypingPresence.deleted_at.is_(None),
        )
    )
    return [{"user_id": str(r.user_id), "status": r.status, "expires_at": r.expires_at.isoformat()} for r in rows.scalars().all()]

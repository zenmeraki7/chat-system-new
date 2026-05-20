from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.conversation import PublicConversationResponse, WidgetConversationStartRequest
from app.schemas.message import PublicMessageResponse, SendTextMessageRequest
from app.services.chat_service import ChatService
from app.services.idempotency_service import IdempotencyService
from app.services.api_key_auth_service import ApiKeyAuthService
from app.repositories.business_repo import BusinessRepository

router = APIRouter(prefix="/public", tags=["Public (Widget)"])


@router.post("/conversations/start", response_model=PublicConversationResponse)
async def start_conversation(
    api_key: str,
    payload: WidgetConversationStartRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the widget when a visitor opens chat for the first time.
    Returns an existing active conversation or creates a new one.
    """
    svc = ChatService(db)
    if not payload.visitor_token:
        raise HTTPException(status_code=400, detail="visitor_token is required")
    principal = await ApiKeyAuthService(db).authenticate(
        api_key,
        required_scope="chat:write",
        expected_environment="live",
    )
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")
    business = await BusinessRepository(db).get_by_id(principal.business_id)
    if not business:
        raise HTTPException(status_code=401, detail="Unauthorized")
    expected_widget_key = f"wpk_{business.public_id}"
    if payload.widget_public_key != expected_widget_key:
        raise HTTPException(status_code=403, detail="Invalid widget key for API key context")
    conversation, _ = await svc.start_or_get_conversation(
        api_key=None,
        visitor_id=payload.visitor_token,
        visitor_name=payload.visitor_name,
        visitor_email=payload.visitor_email,
        business_id=business.id,
    )
    return PublicConversationResponse(
        public_id=conversation.id,
        status=conversation.status,
        created_at=conversation.created_at,
    )


@router.get("/conversations/history", response_model=List[PublicMessageResponse])
async def get_visitor_history(
    api_key: str,
    visitor_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the widget on load to restore message history for a returning visitor.
    visitor_id is stored in the visitor's localStorage.
    """
    svc = ChatService(db)
    messages = await svc.get_visitor_messages(api_key=api_key, visitor_id=visitor_id)
    return [
        PublicMessageResponse(
            public_id=message.id,
            conversation_public_id=message.conversation_id,
            direction=message.direction,
            sender_type=message.sender_type,
            message_type=message.message_kind,
            content_text=message.content_text or message.content,
            status=message.status,
            created_at=message.created_at,
            is_redacted=bool(message.redacted_at or message.content_redacted_at),
        )
        for message in messages
    ]


@router.post("/conversations/message", response_model=dict)
async def send_message(
    api_key: str,
    visitor_id: str,
    payload: SendTextMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    HTTP fallback for sending a message when WebSocket is not available.
    Returns both the user message and the AI reply.
    """
    principal = await ApiKeyAuthService(db).authenticate(
        api_key,
        required_scope="chat:write",
        expected_environment="live",
    )
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")

    idem = IdempotencyService(db)
    request_payload = {
        "api_key": api_key,
        "visitor_id": visitor_id,
        "content": payload.content_text,
        "reply_to_message_public_id": str(payload.reply_to_message_public_id) if payload.reply_to_message_public_id else None,
    }
    replay = await idem.begin_or_replay(
        business_id=principal.business_id,
        key=payload.idempotency_key,
        payload=request_payload,
    )
    if replay is not None:
        return replay

    svc = ChatService(db)
    response = await svc.handle_incoming_message(
        api_key=api_key,
        visitor_id=visitor_id,
        user_content=payload.content_text,
        visitor_name=None,
    )
    await idem.finalize(
        business_id=principal.business_id,
        key=payload.idempotency_key,
        response_json=response,
    )
    return response

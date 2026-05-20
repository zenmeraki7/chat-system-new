import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.chat_service import ChatService
from app.core.exceptions import NotFoundException

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/chat/{api_key}/{visitor_id}")
async def websocket_chat(
    websocket: WebSocket,
    api_key: str,
    visitor_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Real-time WebSocket endpoint for the chat widget.

    Flow:
    1. Connect → validate api_key, load/create conversation
    2. Send existing message history to client
    3. Listen for incoming messages
    4. Save user message, call OpenAI, save reply, send reply back
    """
    await websocket.accept()
    svc = ChatService(db)

    try:
        # Validate api_key and get/create conversation
        try:
            conversation, business = await svc.start_or_get_conversation(
                api_key=api_key, visitor_id=visitor_id
            )
        except NotFoundException as e:
            await websocket.send_json({"type": "error", "message": str(e.detail)})
            await websocket.close(code=4004)
            return

        # Send conversation history on connect
        history_messages = await svc.get_history_for_context(business.id, conversation.id)
        from app.repositories.message_repo import MessageRepository
        msg_repo = MessageRepository(db)
        raw_history = await msg_repo.get_by_conversation(business.id, conversation.id)

        await websocket.send_json({
            "type": "history",
            "conversation_id": str(conversation.id),
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role.value,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in raw_history
            ],
        })

        # Listen for messages
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            if payload.get("type") != "message":
                continue

            user_content = payload.get("content", "").strip()
            if not user_content:
                continue

            # Acknowledge user message received
            await websocket.send_json({"type": "typing", "message": "Assistant is typing..."})

            # Process through chat service
            result = await svc.handle_incoming_message(
                api_key=api_key,
                visitor_id=visitor_id,
                user_content=user_content,
                visitor_name=payload.get("visitor_name"),
            )

            # Send AI reply back to client
            await websocket.send_json({
                "type": "message",
                "user_message": result["user_message"],
                "ai_message": result["ai_message"],
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": "Internal server error"})
        except Exception:
            pass

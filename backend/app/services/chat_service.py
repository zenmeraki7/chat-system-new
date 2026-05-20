from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.business_repo import BusinessRepository
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.message_repo import MessageRepository
from app.models.message import Message, MessageRole
from app.core.exceptions import NotFoundException


from app.services.credential_resolver import CredentialResolver
from app.services.send_eligibility_service import SendEligibilityService
from app.services.conversation_service import ConversationService
from sqlalchemy import select
from sqlalchemy import func
from datetime import datetime, timezone
from app.models.business_domains import ContactOptIn, MessageSendAttempt, OutboxEvent
from app.core.exceptions import ForbiddenException
from app.services.api_key_auth_service import ApiKeyAuthService
from app.core.exceptions import BadRequestException
from app.services.conversation_resolver import ConversationResolver


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.business_repo = BusinessRepository(db)
        self.api_key_auth = ApiKeyAuthService(db)
        self.conversation_repo = ConversationRepository(db)
        self.conversation_resolver = ConversationResolver(self.conversation_repo)
        self.message_repo = MessageRepository(db)
        self.credential_resolver = CredentialResolver(db)
        self.send_eligibility = SendEligibilityService(db)
        self.conversation_service = ConversationService(db)

    async def _record_send_attempt(
        self,
        *,
        business_id: UUID,
        message_id: UUID,
        provider: str,
        response_status_code: int | None,
        provider_error_code: str | None,
        provider_error_subcode: str | None,
        failure_message: str | None,
        response_body_redacted: str | None,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        attempt_res = await self.db.execute(
            select(func.max(MessageSendAttempt.attempt_number)).where(
                MessageSendAttempt.business_id == business_id,
                MessageSendAttempt.message_id == message_id,
            )
        )
        current = attempt_res.scalar_one_or_none() or 0
        self.db.add(
            MessageSendAttempt(
                business_id=business_id,
                message_id=message_id,
                attempt_number=int(current) + 1,
                provider=provider,
                response_status_code=response_status_code,
                provider_error_code=provider_error_code,
                provider_error_subcode=provider_error_subcode,
                failure_message=failure_message,
                response_body_redacted=response_body_redacted,
                request_started_at=started_at,
                request_finished_at=finished_at,
                retryable=False if failure_message else None,
            )
        )

    @staticmethod
    def _normalize_visitor_id(visitor_id: str) -> str:
        normalized = (visitor_id or "").strip()
        if not normalized:
            raise BadRequestException("visitor_id is required")
        if len(normalized) > 255:
            raise BadRequestException("visitor_id exceeds maximum length")
        return normalized

    @staticmethod
    def _normalize_email(visitor_email: str | None) -> str | None:
        if visitor_email is None:
            return None
        normalized = visitor_email.strip().lower()
        return normalized or None

    async def start_or_get_conversation(
        self,
        api_key: str | None,
        visitor_id: str,
        visitor_name: str = None,
        visitor_email: str = None,
        business_id: UUID | None = None,
    ):
        visitor_id = self._normalize_visitor_id(visitor_id)
        visitor_email = self._normalize_email(visitor_email)
        if business_id:
            business = await self.business_repo.get_by_id(business_id)
        else:
            principal = await self.api_key_auth.authenticate(
                api_key or "",
                required_scope="chat:write",
                expected_environment="live",
            )
            business = await self.business_repo.get_by_id(principal.business_id) if principal else None
        if not business or business.status != "active":
            raise NotFoundException("Business not found or inactive")

        conversation = await self.conversation_resolver.get_or_create_for_contact_channel(
            business_id=business.id,
            visitor_id=visitor_id,
            channel_id=None,
            visitor_name=visitor_name,
            visitor_email=visitor_email,
        )
        return conversation, business

    async def get_history_for_context(self, business_id: UUID, conversation_id: UUID) -> List[dict]:
        """Returns messages formatted for context."""
        messages = await self.message_repo.get_by_conversation(business_id, conversation_id)
        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
            if msg.role != MessageRole.SYSTEM
        ]

    async def get_visitor_messages(self, api_key: str, visitor_id: str) -> List[Message]:
        """Returns all messages for a visitor across all their conversations."""
        visitor_id = self._normalize_visitor_id(visitor_id)
        principal = await self.api_key_auth.authenticate(
            api_key,
            required_scope="chat:read",
            expected_environment="live",
        )
        business = await self.business_repo.get_by_id(principal.business_id) if principal else None
        if not business:
            raise NotFoundException("Business not found")

        conversations = await self.conversation_repo.get_visitor_conversations(
            visitor_id=visitor_id,
            business_id=business.id,
            channel_id=None,
            limit=50,
        )
        all_messages: List[Message] = []
        for conv in conversations:
            msgs = await self.message_repo.get_by_conversation(business.id, conv.id)
            all_messages.extend(msgs)
        return all_messages

    async def handle_incoming_message(
        self,
        api_key: str,
        visitor_id: str,
        user_content: str,
        visitor_name: str = None,
        channel: str = "widget",
        business_id: UUID | None = None,
        phone_number_id: str | None = None,
    ) -> dict:
        """Save user message, generate reply, save reply, and send to channel if needed."""
        visitor_id = self._normalize_visitor_id(visitor_id)
        conversation, business = await self.start_or_get_conversation(
            api_key, visitor_id, visitor_name, business_id=business_id
        )
        user_seq = await self.conversation_repo.allocate_next_message_sequence(
            business_id=business.id,
            conversation_id=conversation.id,
        )

        # Save user message
        user_msg = await self.message_repo.create_message(
            business_id=business.id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=user_content,
            conversation_sequence=user_seq,
            channel_id=conversation.channel_id,
        )
        await self.conversation_service.record_message_activity(
            business_id=business.id,
            conversation_id=conversation.id,
        )

        # Generate Reply (Placeholder for now)
        ai_content = f"Hi! This is an automated reply to: '{user_content}'. We'll get back to you soon!"
        usage = {"provider": "placeholder", "channel": channel}

        # Save AI reply
        ai_seq = await self.conversation_repo.allocate_next_message_sequence(
            business_id=business.id,
            conversation_id=conversation.id,
        )
        ai_msg = await self.message_repo.create_message(
            business_id=business.id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=ai_content,
            meta=usage,
            conversation_sequence=ai_seq,
            channel_id=conversation.channel_id,
        )
        await self.conversation_service.record_message_activity(
            business_id=business.id,
            conversation_id=conversation.id,
        )

        # If it's from WhatsApp, enqueue outbound send for async worker.
        if channel == "whatsapp":
            if phone_number_id:
                await self.send_eligibility.assert_can_send(
                    business_id=business.id,
                    phone_number_id=phone_number_id,
                )
                token, phone_id = await self.credential_resolver.for_phone_number(
                    business_id=business.id,
                    phone_number_id=phone_number_id,
                )
                opt_in_res = await self.db.execute(
                    select(ContactOptIn).where(
                        ContactOptIn.business_id == business.id,
                        ContactOptIn.contact_id == visitor_id,
                        ContactOptIn.channel_type == "whatsapp",
                        ContactOptIn.phone_number_id == phone_id,
                        ContactOptIn.opt_in_status == "opted_in",
                        ContactOptIn.deleted_at.is_(None),
                    )
                )
                if not opt_in_res.scalar_one_or_none():
                    raise ForbiddenException("Recipient has not opted in for this WhatsApp phone number")
            else:
                _, phone_id = await self.business_repo.get_whatsapp_credentials(business.id)
            ai_msg.status = "queued"
            ai_msg.channel_type = "whatsapp"
            self.db.add(
                OutboxEvent(
                    business_id=business.id,
                    operation_id=str(ai_msg.id),
                    event_type="whatsapp.send.outbound",
                    payload_json={
                        "message_id": str(ai_msg.id),
                        "business_id": str(business.id),
                        "to": visitor_id,
                        "text": ai_content,
                        "phone_number_id": phone_id,
                        "contact_id": visitor_id,
                        "source": "automation",
                    },
                    status="pending",
                )
            )

        return {
            "conversation_id": str(conversation.id),
            "user_message": {"id": str(user_msg.id), "content": user_content, "role": "user"},
            "ai_message": {"id": str(ai_msg.id), "content": ai_content, "role": "assistant"},
        }

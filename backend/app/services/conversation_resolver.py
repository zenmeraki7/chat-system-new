from uuid import UUID
from app.repositories.conversation_repo import ConversationRepository
from app.models.conversation import Conversation


class ConversationResolver:
    def __init__(self, repo: ConversationRepository):
        self.repo = repo

    async def get_or_create_for_contact_channel(
        self,
        *,
        business_id: UUID,
        visitor_id: str,
        channel_id: UUID | None,
        visitor_name: str | None = None,
        visitor_email: str | None = None,
    ) -> Conversation:
        return await self.repo.get_or_create_for_visitor(
            business_id=business_id,
            visitor_id=visitor_id,
            visitor_name=visitor_name,
            visitor_email=visitor_email,
            channel_id=channel_id,
        )

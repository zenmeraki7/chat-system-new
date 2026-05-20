from typing import Optional, List
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only
from app.repositories.base import TenantMutableRepository
from app.models.conversation import Conversation, ConversationStatus
from app.models.business_domains import ConversationTag
from app.core.exceptions import ForbiddenException


class ConversationRepository(TenantMutableRepository[Conversation]):
    def __init__(self, db: AsyncSession):
        super().__init__(Conversation, db)

    async def get_by_business(
        self, business_id: UUID, skip: int = 0, limit: int = 50
    ) -> List[Conversation]:
        # Backward-compatible wrapper; callers should move to list_for_business cursor pagination.
        return await self.list_for_business(business_id=business_id, limit=limit)

    async def list_for_business(
        self,
        *,
        business_id: UUID,
        limit: int = 50,
        cursor_last_message_at: datetime | None = None,
        cursor_id: UUID | None = None,
        status: str | None = None,
        assigned_user_id: UUID | None = None,
        channel_id: UUID | None = None,
        priority: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        include_archived: bool = False,
        include_deleted: bool = False,
    ) -> List[Conversation]:
        limit = min(max(limit, 1), 100)
        stmt = select(Conversation).options(
            load_only(
                Conversation.id,
                Conversation.business_id,
                Conversation.status,
                Conversation.visitor_id,
                Conversation.visitor_name,
                Conversation.last_message_at,
                Conversation.updated_at,
                Conversation.assigned_user_id,
                Conversation.channel_id,
            )
        ).where(Conversation.business_id == business_id)
        if not include_deleted:
            stmt = stmt.where(Conversation.deleted_at.is_(None))
        if not include_archived:
            stmt = stmt.where(Conversation.archived_at.is_(None))
        if status is not None:
            stmt = stmt.where(Conversation.status == status)
        if assigned_user_id is not None:
            stmt = stmt.where(Conversation.assigned_user_id == assigned_user_id)
        if channel_id is not None:
            stmt = stmt.where(Conversation.channel_id == channel_id)
        if priority is not None:
            stmt = stmt.where(Conversation.priority == priority)
        if tag is not None:
            stmt = stmt.join(ConversationTag, ConversationTag.conversation_id == Conversation.id).where(
                ConversationTag.tag == tag,
                ConversationTag.deleted_at.is_(None),
            )
        if search is not None and search.strip():
            q = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Conversation.visitor_id.ilike(q),
                    Conversation.visitor_name.ilike(q),
                    Conversation.visitor_email.ilike(q),
                )
            )
        if cursor_last_message_at is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    Conversation.last_message_at < cursor_last_message_at,
                    and_(
                        Conversation.last_message_at == cursor_last_message_at,
                        Conversation.id < cursor_id,
                    ),
                )
            )
        stmt = stmt.order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_or_create_for_visitor(
        self,
        business_id: UUID,
        visitor_id: str,
        visitor_name: Optional[str] = None,
        visitor_email: Optional[str] = None,
        channel_id: UUID | None = None,
    ) -> Conversation:
        normalized_email = visitor_email.strip().lower() if visitor_email else None
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.business_id == business_id,
                Conversation.channel_id == channel_id,
                Conversation.visitor_id == visitor_id,
                Conversation.status.in_([ConversationStatus.OPEN.value, ConversationStatus.PENDING.value]),
                Conversation.deleted_at.is_(None),
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(1)
        )
        conversation = result.scalars().first()

        if not conversation:
            try:
                async with self.db.begin_nested():
                    conversation = await self.create(
                        business_id=business_id,
                        channel_id=channel_id,
                        visitor_id=visitor_id,
                        visitor_name=visitor_name,
                        visitor_email=normalized_email,
                    )
            except IntegrityError:
                retry = await self.db.execute(
                    select(Conversation).where(
                        Conversation.business_id == business_id,
                        Conversation.channel_id == channel_id,
                        Conversation.visitor_id == visitor_id,
                        Conversation.status.in_([ConversationStatus.OPEN.value, ConversationStatus.PENDING.value]),
                        Conversation.deleted_at.is_(None),
                    )
                    .order_by(Conversation.created_at.desc(), Conversation.id.desc())
                    .limit(1)
                )
                conversation = retry.scalars().first()
                if conversation is None:
                    raise
        else:
            # Minimal enrichment for legacy visitor metadata while contact model migration is in progress.
            if visitor_name and not conversation.visitor_name:
                conversation.visitor_name = visitor_name
            if normalized_email and not conversation.visitor_email:
                conversation.visitor_email = normalized_email
            await self.db.flush()
        return conversation

    async def get_for_business(self, business_id: UUID, conversation_id: UUID) -> Optional[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.business_id == business_id,
                Conversation.id == conversation_id,
                Conversation.deleted_at.is_(None),
                Conversation.archived_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_visitor_conversations(
        self,
        visitor_id: str,
        business_id: UUID,
        channel_id: UUID | None = None,
        limit: int = 50,
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> List[Conversation]:
        limit = min(max(limit, 1), 100)
        stmt = (
            select(Conversation)
            .where(
                Conversation.visitor_id == visitor_id,
                Conversation.business_id == business_id,
                Conversation.deleted_at.is_(None),
            )
        )
        if channel_id is not None:
            stmt = stmt.where(Conversation.channel_id == channel_id)
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                or_(
                    Conversation.created_at < before_created_at,
                    and_(
                        Conversation.created_at == before_created_at,
                        Conversation.id < before_id,
                    ),
                )
            )
        stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_business(self, *, business_id: UUID, status: str | None = None) -> int:
        stmt = select(func.count()).where(
            Conversation.business_id == business_id,
            Conversation.deleted_at.is_(None),
        )
        if status is not None:
            stmt = stmt.where(Conversation.status == status)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_for_update(self, business_id: UUID, conversation_id: UUID) -> Optional[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.business_id == business_id,
                Conversation.id == conversation_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def update_for_business(
        self,
        *,
        business_id: UUID,
        id: UUID,
        values: dict,
    ) -> Optional[Conversation]:
        if not values:
            raise ValueError("No update fields provided")
        allowed_fields = {
            "visitor_name",
            "visitor_email",
            "assigned_user_id",
            "assigned_team_id",
            "priority",
            "status",
            "archived_at",
            "last_message_at",
            "disabled_at",
        }
        unknown_fields = set(values.keys()) - allowed_fields
        if unknown_fields:
            raise ValueError(f"Unknown or forbidden update fields: {', '.join(sorted(unknown_fields))}")
        stmt = (
            update(Conversation)
            .where(
                Conversation.business_id == business_id,
                Conversation.id == id,
                Conversation.deleted_at.is_(None),
            )
            .values(**values)
            .returning(Conversation)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def allocate_next_message_sequence(self, business_id: UUID, conversation_id: UUID) -> int:
        conversation = await self.get_for_update(business_id, conversation_id)
        if not conversation:
            raise ForbiddenException("Conversation not found for tenant")
        current = conversation.next_message_sequence
        conversation.next_message_sequence = current + 1
        await self.db.flush()
        return current

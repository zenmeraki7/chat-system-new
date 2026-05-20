from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.business_repo import BusinessRepository
from app.core.exceptions import ForbiddenException


class TenantResolver:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BusinessRepository(db)

    async def require_active_membership(self, business_id: UUID, user_id: UUID):
        membership = await self.repo.get_membership(business_id, user_id)
        if not membership:
            raise ForbiddenException("User does not have active membership for this business")
        if membership.user and membership.user.deleted_at is not None:
            raise ForbiddenException("User account is not active")
        return membership

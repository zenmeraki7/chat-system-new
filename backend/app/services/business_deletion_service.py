from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.business_repo import BusinessRepository
from app.core.exceptions import NotFoundException
from app.services.audit_log_service import AuditLogService


class BusinessDeletionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BusinessRepository(db)
        self.audit = AuditLogService(db)

    async def request_deletion(self, business_id: UUID, actor_user_id: UUID, retention_days: int = 30) -> datetime:
        business = await self.repo.get_by_id(business_id)
        if not business:
            raise NotFoundException("Business not found")
        purge_after = datetime.now(timezone.utc) + timedelta(days=retention_days)
        business.status = "deletion_requested"
        await self.db.commit()
        await self.audit.write(
            action="business.deletion.requested",
            resource_type="business",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="user",
            actor_id=str(actor_user_id),
            resource_id=str(business_id),
            details={"retention_days": retention_days, "purge_after": purge_after.isoformat()},
        )
        return purge_after

    async def execute_after_retention_window(self, business_id: UUID, actor_user_id: UUID) -> None:
        business = await self.repo.get_by_id(business_id)
        if not business:
            return
        business.status = "deleted"
        business.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.audit.write(
            action="business.deletion.executed",
            resource_type="business",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="system",
            actor_id=str(actor_user_id),
            resource_id=str(business_id),
        )

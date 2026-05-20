from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.audit_log_repo import AuditLogRepository


class AuditLogService:
    def __init__(self, db: AsyncSession):
        self.repo = AuditLogRepository(db)

    async def write(
        self,
        action: str,
        resource_type: str,
        status: str = "success",
        business_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        await self.repo.record(
            action=action,
            resource_type=resource_type,
            status=status,
            business_id=business_id,
            user_id=user_id,
            actor_type=actor_type,
            actor_id=actor_id,
            operation_id=operation_id,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
        )

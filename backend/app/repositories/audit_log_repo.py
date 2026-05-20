from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import AppendOnlyRepository
from app.models.business_domains import AuditLog


class AuditLogRepository(AppendOnlyRepository[AuditLog]):
    def __init__(self, db: AsyncSession):
        super().__init__(AuditLog, db)

    async def record(
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
    ) -> AuditLog:
        return await self.append(
            business_id=business_id,
            user_id=user_id,
            actor_type=actor_type,
            actor_id=actor_id,
            operation_id=operation_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
        )

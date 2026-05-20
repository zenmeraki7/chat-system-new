from dataclasses import dataclass
from uuid import UUID
from app.repositories.api_key_repo import ApiKeyRepository
from app.repositories.business_repo import BusinessRepository
from app.services.audit_log_service import AuditLogService
from app.core.exceptions import NotFoundException
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ApiKeyRotationResult:
    api_key_id: UUID
    key_prefix: str
    raw_api_key: str
    environment: str


class ApiKeyRotationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.business_repo = BusinessRepository(db)
        self.api_key_repo = ApiKeyRepository(db)
        self.audit = AuditLogService(db)

    async def rotate_key(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        scopes: list[str] | None = None,
        environment: str = "live",
        name: str = "Rotated key",
        revoke_previous_in_environment: bool = False,
    ) -> ApiKeyRotationResult:
        business = await self.business_repo.get_by_id_for_update(business_id)
        if not business or business.status != "active":
            raise NotFoundException("Business not found or inactive")

        if revoke_previous_in_environment:
            active = await self.api_key_repo.list_active_keys_for_business(
                business_id=business_id,
                environment=environment,
            )
            for key in active:
                await self.api_key_repo.revoke_key(business_id=business_id, api_key_id=key.id)

        row, raw_key = await self.api_key_repo.create_hashed_key(
            business_id=business_id,
            name=name,
            scopes=scopes or ["chat:write", "chat:read"],
            created_by_user_id=actor_user_id,
            environment=environment,
        )
        await self.audit.write(
            action="business.api_key.created",
            resource_type="business_api_key",
            business_id=business_id,
            user_id=actor_user_id,
            actor_type="user",
            actor_id=str(actor_user_id),
            resource_id=str(row.id),
            details={"key_prefix": row.key_prefix, "environment": environment},
        )
        if revoke_previous_in_environment:
            await self.audit.write(
                action="business.api_key.revoke_previous",
                resource_type="business_api_key",
                business_id=business_id,
                user_id=actor_user_id,
                actor_type="user",
                actor_id=str(actor_user_id),
                resource_id=str(row.id),
                details={"revocation_reason": "rotated", "environment": environment},
            )
        return ApiKeyRotationResult(
            api_key_id=row.id,
            key_prefix=row.key_prefix,
            raw_api_key=raw_key,
            environment=row.environment,
        )

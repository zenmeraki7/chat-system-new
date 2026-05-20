from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.repositories.base import SecretRepository
from app.models.business_domains import BusinessApiKey
from app.core.security import generate_business_api_key


class ApiKeyRepository(SecretRepository[BusinessApiKey]):
    def __init__(self, db: AsyncSession):
        super().__init__(BusinessApiKey, db)

    async def create_hashed_key(
        self,
        *,
        business_id: UUID,
        name: str,
        scopes: list[str],
        created_by_user_id: UUID | None = None,
        environment: str = "live",
    ) -> tuple[BusinessApiKey, str]:
        raw_key, prefix, key_hash = generate_business_api_key()
        row = BusinessApiKey(
            business_id=business_id,
            key_prefix=prefix,
            key_hash=key_hash,
            name=name,
            scopes=scopes,
            created_by_user_id=created_by_user_id,
            environment=environment,
        )
        self.db.add(row)
        await self.db.flush()
        return row, raw_key

    async def list_active_keys_for_business(self, *, business_id: UUID, environment: str | None = None) -> list[BusinessApiKey]:
        stmt = select(BusinessApiKey).where(
            BusinessApiKey.business_id == business_id,
            BusinessApiKey.revoked_at.is_(None),
            BusinessApiKey.deleted_at.is_(None),
        )
        if environment is not None:
            stmt = stmt.where(BusinessApiKey.environment == environment)
        result = await self.db.execute(stmt.order_by(BusinessApiKey.created_at.desc(), BusinessApiKey.id.desc()))
        return list(result.scalars().all())

    async def revoke_key(self, *, business_id: UUID, api_key_id: UUID) -> bool:
        result = await self.db.execute(
            update(BusinessApiKey)
            .where(
                BusinessApiKey.business_id == business_id,
                BusinessApiKey.id == api_key_id,
                BusinessApiKey.revoked_at.is_(None),
                BusinessApiKey.deleted_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        return result.rowcount == 1

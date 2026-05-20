from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.business_domains import ProviderErrorMapping


class ProviderErrorNormalizer:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve(self, provider: str, error_code: str | None, error_subcode: str | None):
        if not error_code:
            return None
        specific = await self.db.execute(
            select(ProviderErrorMapping).where(
                ProviderErrorMapping.provider == provider,
                ProviderErrorMapping.error_code == error_code,
                ProviderErrorMapping.error_subcode == error_subcode,
                ProviderErrorMapping.deleted_at.is_(None),
            )
        )
        row = specific.scalar_one_or_none()
        if row:
            return row
        fallback = await self.db.execute(
            select(ProviderErrorMapping).where(
                ProviderErrorMapping.provider == provider,
                ProviderErrorMapping.error_code == error_code,
                ProviderErrorMapping.error_subcode.is_(None),
                ProviderErrorMapping.deleted_at.is_(None),
            )
        )
        return fallback.scalar_one_or_none()

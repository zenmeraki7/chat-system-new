from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import SecretRepository
from app.models.business_domains import WebhookSubscription
from app.core.security import hash_token


class WebhookSecretRepository(SecretRepository[WebhookSubscription]):
    def __init__(self, db: AsyncSession):
        super().__init__(WebhookSubscription, db)

    async def create_hashed_secret(
        self,
        *,
        business_id: UUID,
        provider: str,
        verify_token: str,
        waba_id: str | None,
        phone_number_id: str | None,
        status: str = "active",
        subscribed_fields: list[str] | None = None,
        environment: str = "live",
    ) -> WebhookSubscription:
        row = WebhookSubscription(
            business_id=business_id,
            provider=provider,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            verify_token_hash=hash_token(verify_token),
            status=status,
            subscribed_fields=subscribed_fields or [],
            environment=environment,
        )
        self.db.add(row)
        await self.db.flush()
        return row

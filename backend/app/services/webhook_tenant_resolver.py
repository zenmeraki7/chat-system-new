from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.business_repo import BusinessRepository
from app.core.exceptions import NotFoundException


class WebhookTenantResolver:
    def __init__(self, db: AsyncSession):
        self.repo = BusinessRepository(db)

    async def resolve(self, waba_id: str, phone_number_id: str):
        business, channel_id = await self.repo.resolve_webhook_tenant(waba_id=waba_id, phone_number_id=phone_number_id)
        if not business:
            raise NotFoundException("Unable to resolve webhook tenant from WABA + phone number")
        return business, channel_id

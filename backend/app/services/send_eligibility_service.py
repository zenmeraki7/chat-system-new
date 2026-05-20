from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ForbiddenException
from app.services.phone_number_resolver import PhoneNumberResolver


class SendEligibilityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.phone_resolver = PhoneNumberResolver(db)

    async def assert_can_send(self, business_id: UUID, phone_number_id: str):
        phone = await self.phone_resolver.resolve_active_for_business(business_id, phone_number_id)
        if phone.sending_status and phone.sending_status.lower() in {"disabled", "blocked"}:
            raise ForbiddenException("Phone number sending is blocked")
        return phone

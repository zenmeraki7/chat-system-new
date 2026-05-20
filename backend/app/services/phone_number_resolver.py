from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.business_domains import WhatsAppPhoneNumber


class PhoneNumberResolver:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_active_for_business(self, business_id: UUID, phone_number_id: str) -> WhatsAppPhoneNumber:
        res = await self.db.execute(
            select(WhatsAppPhoneNumber).where(
                WhatsAppPhoneNumber.business_id == business_id,
                WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                WhatsAppPhoneNumber.disconnected_at.is_(None),
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
        )
        phone = res.scalar_one_or_none()
        if not phone:
            raise NotFoundException("Phone number not found for business")
        if phone.disabled_at is not None or (phone.status and phone.status.lower() not in {"active", "enabled"}):
            raise ForbiddenException("Phone number is not active")
        return phone

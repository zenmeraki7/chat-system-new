from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ForbiddenException
from app.services.phone_number_resolver import PhoneNumberResolver
from app.services.whatsapp_phone_readiness import whatsapp_phone_readiness_policy


class SendEligibilityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.phone_resolver = PhoneNumberResolver(db)

    async def assert_can_send(self, business_id: UUID, phone_number_id: str):
        phone = await self.phone_resolver.resolve_active_for_business(business_id, phone_number_id)
        if phone.sending_status and phone.sending_status.lower() in {"disabled", "blocked"}:
            raise ForbiddenException("Phone number sending is blocked")
        readiness = whatsapp_phone_readiness_policy.evaluate(
            {
                "code_verification_status": phone.verification_status,
                "status": phone.status,
            }
        )
        if not readiness.ready:
            raise ForbiddenException(f"Phone number is still provisioning: {readiness.reason}")
        health_status = str(phone.last_health_status or "").strip().lower()
        if health_status in {"pending", "error", "degraded"}:
            raise ForbiddenException(f"Phone number provisioning is not healthy yet: {health_status}")
        return phone

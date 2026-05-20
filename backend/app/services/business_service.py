from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.business_repo import BusinessRepository
from app.core.exceptions import NotFoundException, BadRequestException
from app.config import settings
from app.models.business import Business
from app.services.api_key_rotation_service import ApiKeyRotationService


class BusinessService:
    def __init__(self, db: AsyncSession):
        self.repo = BusinessRepository(db)

    @staticmethod
    def serialize_business_profile(business: Business) -> dict:
        return {
            "public_id": business.public_id,
            "name": business.name,
            "status": business.status,
            "created_at": business.created_at,
            "updated_at": business.updated_at,
        }

    async def get_business_profile(self, business_id: UUID) -> dict:
        business = await self.repo.get_business_with_profile(business_id)
        if not business:
            raise NotFoundException("Business not found")
        return self.serialize_business_profile(business)

    async def get_widget_script(self, business_id: UUID) -> dict:
        business = await self.repo.get_business_with_profile(business_id)
        if not business:
            raise NotFoundException("Business not found")

        widget_public_key = f"wpk_{business.public_id}"
        return {
            "script_url": f"{settings.WIDGET_BASE_URL}/widget.js",
            "widget_public_key": widget_public_key,
            "business_public_id": business.public_id,
        }

    async def get_widget_settings(self, business_id: UUID) -> dict:
        business = await self.repo.get_business_with_profile(business_id)
        if not business:
            raise NotFoundException("Business not found")
        return {
            "widget_color": business.widget_settings.widget_color if business.widget_settings else "#6366f1",
            "widget_title": business.widget_settings.widget_title if business.widget_settings else "Chat with us",
            "updated_at": business.updated_at,
        }

    async def get_ai_settings(self, business_id: UUID) -> dict:
        business = await self.repo.get_business_with_profile(business_id)
        if not business:
            raise NotFoundException("Business not found")
        return {
            "system_prompt": business.ai_settings.system_prompt if business.ai_settings else "",
            "prompt_version": 1,
            "updated_at": business.updated_at,
        }

    async def update_settings(self, business_id: UUID, **kwargs):
        if not any(value is not None for value in kwargs.values()):
            raise BadRequestException("No update fields provided")
        await self.repo.upsert_business_settings(
            business_id=business_id,
            name=kwargs.get("name"),
            system_prompt=kwargs.get("system_prompt"),
            widget_color=kwargs.get("widget_color"),
            widget_title=kwargs.get("widget_title"),
        )

    async def regenerate_key(self, business_id: UUID, actor_user_id: UUID):
        return await ApiKeyRotationService(self.repo.db).rotate_key(
            actor_user_id=actor_user_id,
            business_id=business_id,
            scopes=["chat:write", "chat:read"],
            environment="live",
            name="Regenerated key",
            revoke_previous_in_environment=False,
        )

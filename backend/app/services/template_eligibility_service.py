from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ForbiddenException
from app.models.business_domains import WhatsAppMessageTemplate


class TemplateEligibilityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def assert_template_synced(self, business_id: UUID, waba_id: str, template_name: str, language: str):
        res = await self.db.execute(
            select(WhatsAppMessageTemplate).where(
                WhatsAppMessageTemplate.business_id == business_id,
                WhatsAppMessageTemplate.waba_id == waba_id,
                WhatsAppMessageTemplate.name == template_name,
                WhatsAppMessageTemplate.language == language,
                WhatsAppMessageTemplate.deleted_at.is_(None),
            )
        )
        template = res.scalar_one_or_none()
        if not template:
            raise ForbiddenException("Template is not synced for this WABA")
        if template.status and template.status.lower() not in {"approved", "active"}:
            raise ForbiddenException("Template is not in sendable status")
        return template

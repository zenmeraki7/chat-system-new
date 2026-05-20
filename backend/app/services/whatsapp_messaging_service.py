from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.credential_resolver import CredentialResolver
from app.services.send_eligibility_service import SendEligibilityService
from app.services.sending_policy_service import SendingPolicyService
from app.services.template_eligibility_service import TemplateEligibilityService
from app.services.whatsapp_client import whatsapp_cloud_client, WhatsAppClientError
from app.services.whatsapp_domain_policy import whatsapp_domain_policy
from app.core.exceptions import ForbiddenException


@dataclass
class WhatsAppSendResult:
    provider_payload: dict
    conversation_class: str


class WhatsAppMessagingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.credentials = CredentialResolver(db)
        self.send_eligibility = SendEligibilityService(db)
        self.sending_policy = SendingPolicyService(db)
        self.template_eligibility = TemplateEligibilityService(db)

    async def send_text(
        self,
        *,
        business_id: UUID,
        to: str,
        text: str,
        phone_number_id: str,
        contact_id: str,
    ) -> WhatsAppSendResult:
        await self.send_eligibility.assert_can_send(business_id=business_id, phone_number_id=phone_number_id)
        await self.sending_policy.assert_allowed_now(business_id)
        await self.sending_policy.assert_frequency_cap(
            business_id=business_id,
            contact_id=contact_id,
            channel_type="whatsapp",
            max_messages=100,
        )
        token, resolved_phone = await self.credentials.for_phone_number(business_id=business_id, phone_number_id=phone_number_id)
        classification = whatsapp_domain_policy.classify(template_category=None)
        payload = await whatsapp_cloud_client.send_text(
            api_version=settings.META_GRAPH_API_VERSION or "v21.0",
            phone_number_id=resolved_phone,
            token=token,
            to=to,
            body=text,
        )
        return WhatsAppSendResult(provider_payload=payload, conversation_class=classification.conversation_class)

    async def send_template(
        self,
        *,
        business_id: UUID,
        to: str,
        phone_number_id: str,
        waba_id: str,
        template_name: str,
        language: str,
        template_category: str,
        components: list[dict] | None = None,
    ) -> WhatsAppSendResult:
        template = await self.template_eligibility.assert_template_synced(
            business_id=business_id,
            waba_id=waba_id,
            template_name=template_name,
            language=language,
        )
        classification = whatsapp_domain_policy.classify(template_category=template_category or template.category)
        if not classification.requires_template_approval:
            raise ForbiddenException("Template policy classification failed")
        token, resolved_phone = await self.credentials.for_phone_number(business_id=business_id, phone_number_id=phone_number_id)
        payload = await whatsapp_cloud_client.send_template(
            api_version=settings.META_GRAPH_API_VERSION or "v21.0",
            phone_number_id=resolved_phone,
            token=token,
            to=to,
            name=template_name,
            language=language,
            components=components,
        )
        return WhatsAppSendResult(provider_payload=payload, conversation_class=classification.conversation_class)


def map_client_error(exc: WhatsAppClientError) -> tuple[int | None, str | None, str | None, str]:
    return exc.status_code, exc.provider_error_code, exc.provider_error_subcode, str(exc)


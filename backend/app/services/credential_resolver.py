from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.exceptions import ForbiddenException, NotFoundException
from app.services.token_crypto_service import token_crypto_service
from app.models.business_domains import (
    WhatsAppPhoneNumber,
    OAuthCredential,
    ProviderAsset,
    BusinessProviderAssetLink,
)


class CredentialResolver:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_phone_number(self, business_id: UUID, phone_number_id: str) -> tuple[str, str]:
        phone_res = await self.db.execute(
            select(WhatsAppPhoneNumber).where(
                WhatsAppPhoneNumber.business_id == business_id,
                WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                WhatsAppPhoneNumber.environment == "live",
                WhatsAppPhoneNumber.disconnected_at.is_(None),
            )
        )
        phone = phone_res.scalar_one_or_none()
        if not phone:
            raise NotFoundException("Phone number not found for tenant")
        if phone.sending_status and phone.sending_status.lower() == "disabled":
            raise ForbiddenException("Phone number is disabled for sending")
        if phone.disabled_at is not None or phone.status.lower() != "active":
            raise ForbiddenException("Phone number is not active for sending")

        ownership_res = await self.db.execute(
            select(BusinessProviderAssetLink.id)
            .join(ProviderAsset, ProviderAsset.id == BusinessProviderAssetLink.provider_asset_id)
            .where(
                BusinessProviderAssetLink.business_id == business_id,
                ProviderAsset.provider == "meta",
                ProviderAsset.asset_type == "whatsapp_phone_number",
                ProviderAsset.external_id == phone_number_id,
                BusinessProviderAssetLink.deleted_at.is_(None),
                ProviderAsset.deleted_at.is_(None),
            )
        )
        if ownership_res.scalar_one_or_none() is None:
            raise ForbiddenException("Phone number ownership is not verified for this business")

        cred_res = await self.db.execute(
            select(OAuthCredential).where(
                OAuthCredential.business_id == business_id,
                OAuthCredential.provider == "whatsapp",
                OAuthCredential.environment == "live",
                OAuthCredential.revoked_at.is_(None),
            ).order_by(OAuthCredential.created_at.desc())
        )
        credential = cred_res.scalars().first()
        if not credential:
            raise ForbiddenException("No active WhatsApp credential for this tenant")

        scopes = credential.scopes or []
        if scopes and not any(s in scopes for s in ["whatsapp_business_management", "whatsapp_business_messaging", "*"]):
            raise ForbiddenException("Credential does not contain required WhatsApp scopes")

        token = token_crypto_service.decrypt(credential.access_token_ciphertext)
        return token, phone_number_id

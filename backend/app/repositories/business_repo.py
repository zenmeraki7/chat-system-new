from typing import Optional
from uuid import UUID
import uuid
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.business import Business
from app.models.business_domains import (
    User,
    Role,
    Permission,
    BusinessMembership,
    BusinessWidgetSettings,
    WidgetThemePreset,
    BusinessSettings,
    BusinessAiSettings,
    OAuthCredential,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    WebhookSubscription,
    Channel,
    WhatsAppChannel,
)
from app.core.security import hash_token
from app.services.token_crypto_service import token_crypto_service
from app.repositories.api_key_repo import ApiKeyRepository


class BusinessRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, business_id: UUID) -> Optional[Business]:
        result = await self.db.execute(
            select(Business).where(Business.id == business_id, Business.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, business_id: UUID) -> Optional[Business]:
        result = await self.db.execute(
            select(Business)
            .where(Business.id == business_id, Business.deleted_at.is_(None))
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_business_with_defaults(self, name: str, email: str, password_hash: str) -> tuple[Business, str]:
        owner_role = await self._get_or_create_owner_role()
        user = User(email=email.strip().lower(), password_hash=password_hash, status="active")
        self.db.add(user)
        await self.db.flush()
        normalized_name = re.sub(r"\s+", " ", name.strip()).lower()
        base_slug = re.sub(r"[^a-z0-9]+", "-", normalized_name).strip("-") or "business"
        slug = base_slug
        i = 1
        while await self._slug_exists(slug):
            i += 1
            slug = f"{base_slug}-{i}"
        public_id = f"biz_{uuid.uuid4().hex[:12]}"
        business = Business(
            name=name,
            slug=slug,
            public_id=public_id,
            normalized_name=normalized_name,
            created_by_user_id=user.id,
            status="active",
            onboarding_status="pending",
            billing_status="trial",
            business_type="MERCHANT",
            timezone="UTC",
            default_locale="en",
        )
        self.db.add(business)
        await self.db.flush()

        self.db.add(
            BusinessMembership(
                business_id=business.id,
                user_id=user.id,
                role_id=owner_role.id,
                role_code="owner",
                is_primary_owner=True,
                status="active",
            )
        )
        _default_key, raw_key = await ApiKeyRepository(self.db).create_hashed_key(
            business_id=business.id,
            name="Default key",
            scopes=["chat:write", "chat:read"],
            created_by_user_id=user.id,
            environment="live",
        )
        self.db.add(
            BusinessWidgetSettings(
                business_id=business.id,
                widget_theme_preset_id=(await self._get_or_create_default_widget_theme_preset()).id,
                widget_color="#6366f1",
                widget_title="Chat with us",
            )
        )
        self.db.add(
            BusinessAiSettings(
                business_id=business.id,
                system_prompt="You are a helpful customer support assistant. Be friendly, professional, and concise.",
            )
        )
        self.db.add(BusinessSettings(business_id=business.id))
        await self.db.flush()
        return business, raw_key

    async def _get_or_create_default_widget_theme_preset(self) -> WidgetThemePreset:
        result = await self.db.execute(
            select(WidgetThemePreset).where(
                WidgetThemePreset.name == "default",
                WidgetThemePreset.deleted_at.is_(None),
            )
        )
        preset = result.scalar_one_or_none()
        if preset:
            return preset
        preset = WidgetThemePreset(
            name="default",
            status="active",
            config_json={"widget_color": "#6366f1", "widget_title": "Chat with us"},
        )
        self.db.add(preset)
        await self.db.flush()
        return preset

    async def _slug_exists(self, slug: str) -> bool:
        result = await self.db.execute(
            select(Business.id).where(Business.slug == slug, Business.deleted_at.is_(None))
        )
        return result.scalar_one_or_none() is not None

    async def _get_or_create_owner_role(self) -> Role:
        result = await self.db.execute(select(Role).where(Role.code == "owner"))
        role = result.scalar_one_or_none()
        if role:
            return role
        role = Role(code="owner", name="Owner")
        self.db.add(role)
        await self.db.flush()
        self.db.add(Permission(role_id=role.id, permission_code="*"))
        return role

    async def get_membership(self, business_id: UUID, user_id: UUID) -> Optional[BusinessMembership]:
        result = await self.db.execute(
            select(BusinessMembership)
            .options(
                selectinload(BusinessMembership.role).selectinload(Role.permissions),
                selectinload(BusinessMembership.user),
            )
            .where(
                BusinessMembership.business_id == business_id,
                BusinessMembership.user_id == user_id,
                BusinessMembership.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_first_active_membership(self, business_id: UUID) -> Optional[BusinessMembership]:
        result = await self.db.execute(
            select(BusinessMembership)
            .options(
                selectinload(BusinessMembership.role).selectinload(Role.permissions),
                selectinload(BusinessMembership.user),
            )
            .where(
                BusinessMembership.business_id == business_id,
                BusinessMembership.status == "active",
            )
            .order_by(BusinessMembership.created_at.asc())
        )
        return result.scalars().first()

    async def get_business_with_profile(self, business_id: UUID) -> Optional[Business]:
        result = await self.db.execute(
            select(Business)
            .options(
                selectinload(Business.memberships).selectinload(BusinessMembership.user),
                selectinload(Business.api_keys),
                selectinload(Business.widget_settings),
                selectinload(Business.ai_settings),
                selectinload(Business.whatsapp_business_accounts),
            )
            .where(Business.id == business_id)
        )
        return result.scalar_one_or_none()

    async def upsert_business_settings(
        self,
        business_id: UUID,
        name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        widget_color: Optional[str] = None,
        widget_title: Optional[str] = None,
    ) -> Optional[Business]:
        business = await self.get_business_with_profile(business_id)
        if not business:
            return None
        if name is not None:
            business.name = name
        if system_prompt is not None:
            if business.ai_settings:
                business.ai_settings.system_prompt = system_prompt
            else:
                self.db.add(BusinessAiSettings(business_id=business_id, system_prompt=system_prompt))
        if widget_color is not None or widget_title is not None:
            settings = business.widget_settings or BusinessWidgetSettings(business_id=business_id)
            if widget_color is not None:
                settings.widget_color = widget_color
            if widget_title is not None:
                settings.widget_title = widget_title
            if business.widget_settings is None:
                self.db.add(settings)
        await self.db.flush()
        return await self.get_business_with_profile(business_id)

    async def get_whatsapp_credentials(self, business_id: UUID) -> tuple[Optional[str], Optional[str]]:
        token_result = await self.db.execute(
            select(OAuthCredential.access_token_ciphertext)
            .where(OAuthCredential.business_id == business_id, OAuthCredential.provider == "whatsapp", OAuthCredential.revoked_at.is_(None))
            .order_by(OAuthCredential.created_at.desc())
        )
        token_ciphertext = token_result.scalars().first()
        token = token_crypto_service.decrypt(token_ciphertext) if token_ciphertext else None
        phone_result = await self.db.execute(
            select(WhatsAppPhoneNumber.phone_number_id)
            .where(WhatsAppPhoneNumber.business_id == business_id)
            .order_by(WhatsAppPhoneNumber.created_at.desc())
        )
        return token, phone_result.scalars().first()

    async def get_oauth_credential_for_update(self, business_id: UUID, provider: str) -> Optional[OAuthCredential]:
        result = await self.db.execute(
            select(OAuthCredential)
            .where(
                OAuthCredential.business_id == business_id,
                OAuthCredential.provider == provider,
                OAuthCredential.revoked_at.is_(None),
            )
            .order_by(OAuthCredential.created_at.desc())
            .with_for_update()
        )
        return result.scalars().first()

    async def get_phone_number_for_update(self, business_id: UUID, phone_number_id: str) -> Optional[WhatsAppPhoneNumber]:
        result = await self.db.execute(
            select(WhatsAppPhoneNumber)
            .where(
                WhatsAppPhoneNumber.business_id == business_id,
                WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                WhatsAppPhoneNumber.disconnected_at.is_(None),
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_business_by_waba_id(self, waba_id: str) -> Optional[Business]:
        result = await self.db.execute(
            select(Business)
            .join(WhatsAppBusinessAccount, WhatsAppBusinessAccount.business_id == Business.id)
            .where(WhatsAppBusinessAccount.waba_id == waba_id)
        )
        return result.scalar_one_or_none()

    async def resolve_webhook_tenant(self, waba_id: str, phone_number_id: str) -> tuple[Optional[Business], Optional[str]]:
        business_res = await self.db.execute(
            select(Business)
            .join(WhatsAppBusinessAccount, WhatsAppBusinessAccount.business_id == Business.id)
            .join(WhatsAppPhoneNumber, WhatsAppPhoneNumber.business_id == Business.id)
            .where(
                WhatsAppBusinessAccount.waba_id == waba_id,
                WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                WhatsAppPhoneNumber.disconnected_at.is_(None),
            )
        )
        business = business_res.scalar_one_or_none()
        if not business:
            return None, None

        channel_res = await self.db.execute(
            select(Channel.id)
            .join(WhatsAppChannel, WhatsAppChannel.channel_id == Channel.id)
            .where(
                Channel.business_id == business.id,
                WhatsAppChannel.waba_id == waba_id,
                WhatsAppChannel.phone_number_id == phone_number_id,
            )
            .limit(1)
        )
        channel_id = channel_res.scalars().first()
        return business, str(channel_id) if channel_id else None

    async def get_webhook_subscription_by_token(self, provider: str, verify_token: str) -> Optional[WebhookSubscription]:
        token_hash = hash_token(verify_token)
        result = await self.db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.provider == provider,
                WebhookSubscription.verify_token_hash == token_hash,
                WebhookSubscription.status == "active",
            )
        )
        return result.scalar_one_or_none()

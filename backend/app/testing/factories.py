import uuid
from app.models.business import Business
from app.models.business_domains import (
    User,
    BusinessMembership,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    OAuthCredential,
    WhatsAppMessageTemplate,
    Contact,
    Campaign,
    WebhookEvent,
    UsageLedger,
)
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole


def business_factory(**overrides) -> Business:
    return Business(
        name=overrides.get("name", "Test Business"),
        slug=overrides.get("slug", f"biz-{uuid.uuid4().hex[:8]}"),
        public_id=overrides.get("public_id", f"biz_{uuid.uuid4().hex[:12]}"),
        normalized_name=overrides.get("normalized_name", "test business"),
        created_by_user_id=overrides["created_by_user_id"],
        status=overrides.get("status", "active"),
        onboarding_status=overrides.get("onboarding_status", "pending"),
        billing_status=overrides.get("billing_status", "trial"),
        business_type=overrides.get("business_type", "MERCHANT"),
        data_region=overrides.get("data_region", "US"),
        timezone=overrides.get("timezone", "UTC"),
        default_locale=overrides.get("default_locale", "en"),
    )


def user_factory(email: str, password_hash: str = "hash", **overrides) -> User:
    return User(
        email=email.strip().lower(),
        password_hash=password_hash,
        status=overrides.get("status", "active"),
    )


def membership_factory(business_id, user_id, role_id, **overrides) -> BusinessMembership:
    return BusinessMembership(
        business_id=business_id,
        user_id=user_id,
        role_id=role_id,
        role_code=overrides.get("role_code", "member"),
        status=overrides.get("status", "active"),
        is_primary_owner=overrides.get("is_primary_owner", False),
    )


def waba_factory(business_id, waba_id: str, **overrides) -> WhatsAppBusinessAccount:
    return WhatsAppBusinessAccount(business_id=business_id, waba_id=waba_id, review_status=overrides.get("review_status"))


def phone_number_factory(business_id, phone_number_id: str, **overrides) -> WhatsAppPhoneNumber:
    return WhatsAppPhoneNumber(
        business_id=business_id,
        phone_number_id=phone_number_id,
        environment=overrides.get("environment", "live"),
        status=overrides.get("status", "active"),
    )


def credential_factory(business_id, access_token_ciphertext: str, token_hash: str, **overrides) -> OAuthCredential:
    return OAuthCredential(
        business_id=business_id,
        provider=overrides.get("provider", "whatsapp"),
        credential_owner_type=overrides.get("credential_owner_type", "business"),
        credential_owner_id=overrides.get("credential_owner_id"),
        access_token_ciphertext=access_token_ciphertext,
        token_hash=token_hash,
        scopes=overrides.get("scopes", ["whatsapp_business_messaging"]),
        environment=overrides.get("environment", "live"),
    )


def template_factory(business_id, waba_id: str, name: str, language: str = "en", **overrides) -> WhatsAppMessageTemplate:
    return WhatsAppMessageTemplate(
        business_id=business_id,
        waba_id=waba_id,
        name=name,
        language=language,
        status=overrides.get("status", "approved"),
        components_json=overrides.get("components_json", {}),
    )


def contact_factory(business_id, **overrides) -> Contact:
    return Contact(business_id=business_id, display_name=overrides.get("display_name"), status=overrides.get("status", "active"))


def conversation_factory(business_id, visitor_id: str, **overrides) -> Conversation:
    return Conversation(
        business_id=business_id,
        visitor_id=visitor_id,
        status=overrides.get("status", "open"),
        environment=overrides.get("environment", "live"),
    )


def message_factory(conversation_id, content: str, role: MessageRole = MessageRole.USER, **overrides) -> Message:
    return Message(
        conversation_id=conversation_id,
        business_id=overrides.get("business_id"),
        role=role,
        content=content,
        status=overrides.get("status"),
    )


def campaign_factory(business_id, name: str = "Test Campaign", **overrides) -> Campaign:
    return Campaign(
        business_id=business_id,
        public_id=overrides.get("public_id", f"cmp_{uuid.uuid4().hex[:12]}"),
        name=name,
        status=overrides.get("status", "draft"),
        environment=overrides.get("environment", "live"),
    )


def webhook_event_factory(provider: str, event_id: str, payload_hash: str, raw_payload: dict, **overrides) -> WebhookEvent:
    return WebhookEvent(
        business_id=overrides.get("business_id"),
        provider=provider,
        event_id=event_id,
        payload_hash=payload_hash,
        raw_payload=raw_payload,
        processing_status=overrides.get("processing_status", "pending"),
        status=overrides.get("status", "received"),
    )


def usage_ledger_factory(business_id, source_type: str, source_id: str, usage_type: str, quantity: int, idempotency_key: str, **overrides) -> UsageLedger:
    return UsageLedger(
        business_id=business_id,
        source_type=source_type,
        source_id=source_id,
        usage_type=usage_type,
        quantity=quantity,
        idempotency_key=idempotency_key,
        message_id=overrides.get("message_id"),
        campaign_id=overrides.get("campaign_id"),
        provider_event_id=overrides.get("provider_event_id"),
    )

import asyncio

from fastapi.responses import PlainTextResponse

from app.api.v1 import whatsapp as whatsapp_api
from app.config import settings


def test_connect_missing_scopes_guard_detects_missing_required_scopes():
    missing = whatsapp_api._missing_required_scopes(["business_management"])
    assert "whatsapp_business_management" in missing
    assert "whatsapp_business_messaging" in missing


def test_connect_messages_field_guard_detects_missing_messages_field():
    assert whatsapp_api._has_messages_field(["message_template_status_update"]) is False
    assert whatsapp_api._has_messages_field(["messages"]) is True


def test_webhook_get_verification_returns_plain_text_challenge():
    old_meta = settings.META_WEBHOOK_VERIFY_TOKEN
    old_wa = settings.WHATSAPP_VERIFY_TOKEN
    try:
        settings.META_WEBHOOK_VERIFY_TOKEN = "verify-123"
        settings.WHATSAPP_VERIFY_TOKEN = "fallback-verify"
        response = asyncio.run(
            whatsapp_api.verify_webhook(
                mode="subscribe",
                challenge="98765",
                token="verify-123",
            )
        )
        assert isinstance(response, PlainTextResponse)
        assert response.status_code == 200
        assert response.body == b"98765"
    finally:
        settings.META_WEBHOOK_VERIFY_TOKEN = old_meta
        settings.WHATSAPP_VERIFY_TOKEN = old_wa


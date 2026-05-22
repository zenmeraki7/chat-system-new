from fastapi import APIRouter, Request, Query, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, update, func, select
from app.database import get_db
from app.config import settings
from app.services.chat_service import ChatService
import logging
from datetime import datetime, timezone, timedelta

from app.schemas.business import (
    MetaOAuthCallbackRequest,
    EmbeddedSignupSessionCreateRequest,
    EmbeddedSignupSessionCreateResponse,
    WhatsAppOnboardingStatusResponse,
    WhatsAppSetupDiagnosticsResponse,
    WhatsAppOnboardingDebugResponse,
    WhatsAppOnboardingProbeRequest,
    WhatsAppOnboardingProbeResponse,
    WhatsAppOperationalProjectionResponse,
    WhatsAppOperationalReadinessResponse,
    WhatsAppDiagnosticsResponse,
    OnboardingEventLogItem,
    WebhookInboxDebugItem,
)
from app.api.deps import CurrentActor, require_permissions
from app.services.whatsapp_service import whatsapp_service
from app.repositories.business_repo import BusinessRepository
from app.repositories.webhook_event_repo import WebhookEventRepository
from app.repositories.oauth_credential_repo import OAuthCredentialRepository
from app.repositories.webhook_secret_repo import WebhookSecretRepository
from app.services.audit_log_service import AuditLogService
from app.services.webhook_tenant_resolver import WebhookTenantResolver
from app.services.embedded_signup_service import EmbeddedSignupService
from app.services.campaign_state_service import CampaignStateService
from app.services.token_crypto_service import token_crypto_service
from app.services.waba_subscription_service import waba_subscription_service, WabaSubscriptionServiceError
from app.services.observability_metrics import metrics
from app.services.operation_lock_service import OperationLockService
from app.services.whatsapp_onboarding_state_machine import transition_onboarding_state
from app.services.whatsapp_integration_state_machine import transition_whatsapp_integration_status
from app.services.onboarding_event_ledger_service import OnboardingEventLedgerService
from app.services.whatsapp_onboarding_health_projector import WhatsAppOnboardingHealthProjector
from app.services.whatsapp_phone_readiness import whatsapp_phone_readiness_policy
from app.services.template_graph_sync_service import TemplateGraphSyncService
from app.services.queue_routing_service import classify_outbox_event
from app.models.business_domains import (
    OAuthCredential,
    MetaBusinessAccount,
    WhatsAppBusinessAccount,
    WhatsAppPhoneNumber,
    WhatsAppMessageTemplate,
    WebhookSubscription,
    Campaign,
    WhatsAppIntegration,
    WhatsAppAssetConnectionEvent,
    WebhookEvent,
    ProviderWebhookEvent,
    OutboxEvent,
    ProviderIntegration,
    ProviderAsset,
    BusinessProviderAssetLink,
    EmbeddedSignupSession,
    OnboardingOperation,
    MessageOutbox,
    OnboardingEventLedger,
)
import httpx
import secrets
import hmac
import hashlib
import json
from uuid import UUID
from app.core.security import hash_token

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])
webhook_alias_router = APIRouter(tags=["WhatsApp"])
logger = logging.getLogger(__name__)

WHATSAPP_REQUIRED_SCOPES = {"whatsapp_business_management", "whatsapp_business_messaging"}

def _missing_required_scopes(granted_scopes: list[str]) -> list[str]:
    granted_scope_set = {str(scope).strip() for scope in (granted_scopes or []) if str(scope).strip()}
    if "*" in granted_scope_set:
        return []
    return sorted(WHATSAPP_REQUIRED_SCOPES - granted_scope_set)


def _has_messages_field(subscribed_fields: list[str]) -> bool:
    normalized_fields = {str(field).strip().lower() for field in (subscribed_fields or []) if str(field).strip()}
    return "messages" in normalized_fields


def _derive_whatsapp_webhook_identity(payload: dict, raw: bytes) -> tuple[str, str, str | None]:
    """Return (event_type, dedupe_key, provider_event_id)."""
    event_type = "unknown"
    provider_event_id: str | None = None
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = str(change.get("field") or "unknown")
            value = change.get("value") or {}
            event_type = field
            statuses = value.get("statuses") or []
            if statuses:
                status_obj = statuses[0] or {}
                provider_message_id = str(status_obj.get("id") or "")
                provider_status = str(status_obj.get("status") or "unknown")
                provider_ts = str(status_obj.get("timestamp") or "0")
                provider_event_id = provider_message_id or None
                if provider_message_id:
                    return (
                        event_type,
                        f"whatsapp:{provider_message_id}:{provider_status}:{provider_ts}",
                        provider_event_id,
                    )
            messages = value.get("messages") or []
            if messages:
                msg = messages[0] or {}
                inbound_id = str(msg.get("id") or "")
                inbound_ts = str(msg.get("timestamp") or "0")
                provider_event_id = inbound_id or None
                if inbound_id:
                    return (
                        event_type,
                        f"whatsapp:{inbound_id}:incoming:{inbound_ts}",
                        provider_event_id,
                    )
    fallback = hashlib.sha256(raw).hexdigest()
    return event_type, f"whatsapp:fallback:{fallback}", provider_event_id


@router.post("/embedded-signup/session", response_model=EmbeddedSignupSessionCreateResponse)
async def create_embedded_signup_session(
    payload: EmbeddedSignupSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    expected_origin = payload.expected_origin.strip()
    service = EmbeddedSignupService(db)
    session_row, raw_state = await service.create_session(
        business_id=actor.business.id,
        user_id=actor.user.id,
        expected_origin=expected_origin,
        ttl_minutes=payload.ttl_minutes,
    )
    await db.commit()
    return EmbeddedSignupSessionCreateResponse(
        onboarding_session_id=session_row.id,
        state=raw_state,
        expected_origin=session_row.expected_origin,
        expires_at=session_row.expires_at,
    )

@router.get("/embedded-signup/config")
async def get_embedded_signup_config(
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    app_id = str(settings.META_APP_ID or settings.FB_APP_ID or "").strip()
    config_id = str(getattr(settings, "META_EMBEDDED_SIGNUP_CONFIG_ID", "") or "").strip()
    if not app_id:
        raise HTTPException(status_code=500, detail="Meta app id is not configured")
    if not config_id:
        raise HTTPException(status_code=500, detail="Meta embedded signup config id is not configured")
    graph_version = str(settings.META_GRAPH_API_VERSION or "v21.0").strip()
    return {
        "app_id": app_id,
        "config_id": config_id,
        "oauth_dialog_url": f"https://www.facebook.com/{graph_version}/dialog/oauth",
        "required_scopes": sorted(WHATSAPP_REQUIRED_SCOPES),
        "expected_origin": str(settings.META_EMBEDDED_SIGNUP_EXPECTED_ORIGIN or "https://app.penpal.example"),
    }


@router.get("/onboarding/status", response_model=WhatsAppOnboardingStatusResponse)
async def get_whatsapp_onboarding_status(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    waba_res = await db.execute(
        select(WhatsAppBusinessAccount)
        .where(WhatsAppBusinessAccount.business_id == business.id)
        .order_by(WhatsAppBusinessAccount.created_at.desc())
    )
    waba = waba_res.scalars().first()
    phone_res = await db.execute(
        select(WhatsAppPhoneNumber)
        .where(
            WhatsAppPhoneNumber.business_id == business.id,
            WhatsAppPhoneNumber.disconnected_at.is_(None),
        )
        .order_by(WhatsAppPhoneNumber.created_at.desc())
    )
    phone = phone_res.scalars().first()
    cred_res = await db.execute(
        select(OAuthCredential)
        .where(
            OAuthCredential.business_id == business.id,
            OAuthCredential.provider == "whatsapp",
            OAuthCredential.revoked_at.is_(None),
        )
        .order_by(OAuthCredential.created_at.desc())
    )
    cred = cred_res.scalars().first()
    subscription_res = await db.execute(
        select(WebhookSubscription)
        .where(
            WebhookSubscription.business_id == business.id,
            WebhookSubscription.provider == "whatsapp",
            WebhookSubscription.deleted_at.is_(None),
        )
        .order_by(WebhookSubscription.created_at.desc())
    )
    subscription = subscription_res.scalars().first()
    probe_res = await db.execute(
        select(MessageOutbox)
        .where(
            MessageOutbox.business_id == business.id,
            MessageOutbox.source_type == "onboarding_probe",
            MessageOutbox.deleted_at.is_(None),
        )
        .order_by(MessageOutbox.created_at.desc())
        .limit(1)
    )
    latest_probe = probe_res.scalars().first()
    token_valid = False
    if cred is not None:
        try:
            access_token = token_crypto_service.decrypt(cred.access_token_ciphertext)
            app_id = settings.META_APP_ID or settings.FB_APP_ID
            app_secret = settings.META_APP_SECRET or settings.FB_APP_SECRET
            if app_id and app_secret:
                async with httpx.AsyncClient() as client:
                    debug_url = "https://graph.facebook.com/debug_token"
                    debug_params = {
                        "input_token": access_token,
                        "access_token": f"{app_id}|{app_secret}",
                    }
                    debug_resp = await client.get(debug_url, params=debug_params)
                    token_valid = bool((debug_resp.json().get("data") or {}).get("is_valid"))
        except Exception:
            token_valid = False
    display_name_status = (phone.verification_status if phone else None)
    business_verification_status = "approved" if waba else "pending"
    cloud_api_registered = bool(phone and phone.phone_number_id)
    two_step_verification_required = not cloud_api_registered
    webhook_subscribed = bool(
        subscription
        and str(subscription.status or "").lower() == "active"
        and _has_messages_field(subscription.subscribed_fields or [])
    )
    test_message_passed = bool(latest_probe and str(latest_probe.status or "").lower() in {"sent", "delivered", "read"})

    blocking_reasons: list[dict] = []
    if not token_valid:
        blocking_reasons.append({
            "code": "REAUTH_REQUIRED",
            "title": "Access token is invalid or expired",
            "recovery_action": "Reconnect WhatsApp to refresh the access token.",
        })
    if not phone:
        blocking_reasons.append({
            "code": "PHONE_NUMBER_DETECTED",
            "title": "Phone number not attached",
            "recovery_action": "Attach a sender number in embedded signup.",
        })
    if phone and str(phone.verification_status or "").lower() in {"pending", "unverified"}:
        blocking_reasons.append({
            "code": "PHONE_NUMBER_PENDING_VERIFICATION",
            "title": "Phone verification is pending",
            "recovery_action": "Complete phone verification in Meta Business Suite.",
        })
    if not webhook_subscribed:
        blocking_reasons.append({
            "code": "CLOUD_API_REGISTRATION_REQUIRED",
            "title": "Messages webhook is not subscribed",
            "recovery_action": "Subscribe webhook messages field and verify heartbeat.",
        })
    if cloud_api_registered and not test_message_passed:
        blocking_reasons.append({
            "code": "MESSAGE_TEST_REQUIRED",
            "title": "Operational test message not confirmed",
            "recovery_action": "Run the onboarding probe and verify delivery/read events.",
        })

    if not token_valid:
        onboarding_state = "REAUTH_REQUIRED"
    elif not phone:
        onboarding_state = "PHONE_NUMBER_DETECTED"
    elif str(phone.verification_status or "").lower() in {"pending", "unverified"}:
        onboarding_state = "PHONE_NUMBER_PENDING_VERIFICATION"
    elif not webhook_subscribed:
        onboarding_state = "CLOUD_API_REGISTRATION_REQUIRED"
    elif cloud_api_registered and not test_message_passed:
        onboarding_state = "MESSAGE_TEST_REQUIRED"
    else:
        onboarding_state = "READY_TO_SEND"

    return WhatsAppOnboardingStatusResponse(
        onboarding_state=onboarding_state,
        business_id=business.id,
        waba_id=(waba.waba_id if waba else None),
        phone_number_id=(phone.phone_number_id if phone else None),
        display_phone_number=(phone.display_phone_number if phone else None),
        verified_name=(phone.verified_name if phone else None),
        display_name_status=display_name_status,
        business_verification_status=business_verification_status,
        phone_number_quality_rating=(phone.quality_rating if phone else None),
        messaging_limit_tier=(phone.messaging_limit_tier if phone else None),
        currency=(waba.currency if waba else None),
        timezone=(waba.timezone if waba else None),
        cloud_api_registered=cloud_api_registered,
        two_step_verification_required=two_step_verification_required,
        webhook_subscribed=webhook_subscribed,
        test_message_passed=test_message_passed,
        permissions_granted=(cred.scopes if cred else []),
        token_expires_at=(cred.expires_at if cred else None),
        token_valid=token_valid,
        blocking_reasons=blocking_reasons,
    )


@router.post("/onboarding/probe", response_model=WhatsAppOnboardingProbeResponse)
async def enqueue_onboarding_operational_probe(
    payload: WhatsAppOnboardingProbeRequest,
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    recipient = str(payload.to_phone_e164 or settings.WHATSAPP_ONBOARDING_PROBE_RECIPIENT_E164 or "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="Probe recipient not configured")
    text = str(payload.probe_text or settings.WHATSAPP_ONBOARDING_PROBE_TEXT or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Probe text cannot be empty")
    phone = (
        await db.execute(
            select(WhatsAppPhoneNumber)
            .where(
                WhatsAppPhoneNumber.business_id == business.id,
                WhatsAppPhoneNumber.disconnected_at.is_(None),
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
            .order_by(WhatsAppPhoneNumber.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if phone is None:
        raise HTTPException(status_code=400, detail="No active WhatsApp phone number for probe")
    cooldown_seconds = max(30, int(settings.WHATSAPP_ONBOARDING_PROBE_COOLDOWN_SECONDS or 300))
    cooldown_since = datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)
    existing = (
        await db.execute(
            select(MessageOutbox.id)
            .where(
                MessageOutbox.business_id == business.id,
                MessageOutbox.source_type == "onboarding_probe",
                MessageOutbox.created_at >= cooldown_since,
                MessageOutbox.deleted_at.is_(None),
                MessageOutbox.status.in_(["pending", "sending", "sent"]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Recent onboarding probe already exists; wait for completion")
    idempotency_key = f"onboarding_probe:{business.id}:{int(datetime.now(timezone.utc).timestamp())}"
    row = MessageOutbox(
        business_id=business.id,
        phone_number_id=phone.phone_number_id,
        to_phone_e164=recipient,
        message_type="text",
        payload_json={"text": text},
        source_type="onboarding_probe",
        priority=5,
        scheduled_at=datetime.now(timezone.utc),
        idempotency_key=idempotency_key,
        status="pending",
    )
    db.add(row)
    await db.flush()
    await OnboardingEventLedgerService(db).append(
        business_id=business.id,
        operation_id=f"onboarding_probe_{row.id}",
        event_type="onboarding_operational_probe_enqueued",
        event_status="success",
        merchant_user_id=actor.user.id,
        phone_number_id=phone.phone_number_id,
        graph_response_json={"recipient": recipient, "message_outbox_id": str(row.id)},
    )
    await db.commit()
    return WhatsAppOnboardingProbeResponse(
        status="queued",
        message_outbox_id=row.id,
        idempotency_key=row.idempotency_key,
        recipient=recipient,
    )


@router.get("/onboarding/operational-projection", response_model=WhatsAppOperationalProjectionResponse)
async def get_onboarding_operational_projection(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    projection = await WhatsAppOnboardingHealthProjector(db).project_and_apply(
        business_id=actor.business.id,
        actor_user_id=actor.user.id,
        trigger="projection_endpoint",
    )


@router.get("/operational-readiness", response_model=WhatsAppOperationalReadinessResponse)
async def get_operational_readiness(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    now = datetime.now(timezone.utc)
    app_id = str(settings.META_APP_ID or settings.FB_APP_ID or "").strip()
    app_secret = str(settings.META_APP_SECRET or settings.FB_APP_SECRET or "").strip()

    signup = (
        await db.execute(
            select(EmbeddedSignupSession)
            .where(
                EmbeddedSignupSession.business_id == business.id,
                EmbeddedSignupSession.deleted_at.is_(None),
            )
            .order_by(EmbeddedSignupSession.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    embedded_signup_completed = bool(
        signup is not None and (signup.received_code_at is not None or signup.completed_at is not None)
    )


@router.get("/phone-numbers/operational")
async def list_operational_phone_numbers(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    rows = (
        await db.execute(
            select(WhatsAppPhoneNumber)
            .where(
                WhatsAppPhoneNumber.business_id == actor.business.id,
                WhatsAppPhoneNumber.disconnected_at.is_(None),
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
            .order_by(WhatsAppPhoneNumber.created_at.desc())
        )
    ).scalars().all()
    return {
        "data": [
            {
                "phone_number_id": p.phone_number_id,
                "display_phone_number": p.display_phone_number,
                "verified_name": p.verified_name,
                "verification_status": p.verification_status,
                "status": p.status,
                "sending_status": p.sending_status,
            }
            for p in rows
            if str(p.status or "").lower() == "active" and str(p.sending_status or "").lower() != "disabled"
        ]
    }


@router.get("/test-recipients")
async def list_test_recipients(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    # Config-driven approved recipients for controlled operational probes.
    raw = str(getattr(settings, "WHATSAPP_ONBOARDING_PROBE_RECIPIENT_E164", "") or "").strip()
    recipients = [raw] if raw else []
    return {"data": [{"phone_e164": r, "label": "Operational Probe Recipient"} for r in recipients]}

    credential = (
        await db.execute(
            select(OAuthCredential)
            .where(
                OAuthCredential.business_id == business.id,
                OAuthCredential.provider == "whatsapp",
                OAuthCredential.environment == "live",
                OAuthCredential.revoked_at.is_(None),
                OAuthCredential.deleted_at.is_(None),
            )
            .order_by(OAuthCredential.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    code_exchanged = credential is not None

    waba = (
        await db.execute(
            select(WhatsAppBusinessAccount)
            .where(
                WhatsAppBusinessAccount.business_id == business.id,
                WhatsAppBusinessAccount.deleted_at.is_(None),
            )
            .order_by(WhatsAppBusinessAccount.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    phone = (
        await db.execute(
            select(WhatsAppPhoneNumber)
            .where(
                WhatsAppPhoneNumber.business_id == business.id,
                WhatsAppPhoneNumber.disconnected_at.is_(None),
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
            .order_by(WhatsAppPhoneNumber.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    webhook = (
        await db.execute(
            select(WebhookSubscription)
            .where(
                WebhookSubscription.business_id == business.id,
                WebhookSubscription.provider == "whatsapp",
                WebhookSubscription.deleted_at.is_(None),
            )
            .order_by(WebhookSubscription.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    token_valid = False
    required_scopes_granted = False
    business_fetch_ok = False
    waba_fetch_ok = False
    phone_fetch_ok = False
    phone_belongs_to_waba = False
    waba_subscribed_to_app = False
    messages_webhook_enabled = False
    phone_registered = False
    templates_fetch_ok = False
    can_send_test_message = False
    can_receive_webhook = False
    webhook_last_received_at = webhook.last_webhook_received_at if webhook else None

    access_token: str | None = None
    if credential is not None:
        try:
            access_token = token_crypto_service.decrypt(credential.access_token_ciphertext)
        except Exception:
            access_token = None

    granted_scope_set = {str(scope).strip() for scope in ((credential.scopes if credential else []) or []) if str(scope).strip()}
    required_scopes_granted = bool("*" in granted_scope_set or WHATSAPP_REQUIRED_SCOPES.issubset(granted_scope_set))

    if access_token and app_id and app_secret:
        try:
            async with httpx.AsyncClient() as client:
                debug_resp = await client.get(
                    "https://graph.facebook.com/debug_token",
                    params={"input_token": access_token, "access_token": f"{app_id}|{app_secret}"},
                )
                token_valid = bool((debug_resp.json().get("data") or {}).get("is_valid"))
        except Exception:
            token_valid = False

    if access_token and waba is not None:
        try:
            async with httpx.AsyncClient() as client:
                # token can access WABA
                waba_resp = await client.get(
                    f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{waba.waba_id}",
                    params={"fields": "id", "access_token": access_token},
                )
                if waba_resp.status_code == 200 and str((waba_resp.json() or {}).get("id") or "") == str(waba.waba_id):
                    waba_fetch_ok = True

                # waba belongs to business (best-effort via /{business_id})
                mba = (
                    await db.execute(
                        select(MetaBusinessAccount)
                        .where(
                            MetaBusinessAccount.business_id == business.id,
                            MetaBusinessAccount.deleted_at.is_(None),
                        )
                        .order_by(MetaBusinessAccount.created_at.desc())
                        .limit(1)
                    )
                ).scalars().first()
                if mba is not None:
                    business_resp = await client.get(
                        f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{mba.meta_business_account_id}",
                        params={"fields": "id", "access_token": access_token},
                    )
                    business_fetch_ok = business_resp.status_code == 200 and bool((business_resp.json() or {}).get("id"))
                else:
                    business_fetch_ok = True

                # phone fetch + ownership
                phones_resp = await client.get(
                    f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{waba.waba_id}/phone_numbers",
                    params={"access_token": access_token},
                )
                if phones_resp.status_code == 200:
                    rows = (phones_resp.json() or {}).get("data") or []
                    phone_ids = {str((r or {}).get("id") or "") for r in rows if (r or {}).get("id")}
                    phone_fetch_ok = True
                    if phone is not None and str(phone.phone_number_id) in phone_ids:
                        phone_belongs_to_waba = True

                # subscription checks
                if app_id:
                    verify = await waba_subscription_service.verify_subscription(
                        waba_id=str(waba.waba_id),
                        access_token=access_token,
                        app_id=app_id,
                    )
                    waba_subscribed_to_app = bool(verify.app_subscribed)
                    normalized_fields = {str(f).strip().lower() for f in (verify.subscribed_fields or []) if str(f).strip()}
                    messages_webhook_enabled = "messages" in normalized_fields

                # template fetch check
                tmpl_resp = await client.get(
                    f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{waba.waba_id}/message_templates",
                    params={"fields": "id,name,status,language", "limit": 1, "access_token": access_token},
                )
                templates_fetch_ok = tmpl_resp.status_code == 200
        except Exception:
            pass

    if access_token and phone is not None:
        try:
            profile = await whatsapp_service.get_phone_number_operational_profile(
                phone_number_id=phone.phone_number_id,
                token=access_token,
            )
            readiness = whatsapp_phone_readiness_policy.evaluate(profile)
            phone_registered = readiness.ready
        except Exception:
            phone_registered = False

    # Operational probe evidence
    probe_outbox = (
        await db.execute(
            select(MessageOutbox)
            .where(
                MessageOutbox.business_id == business.id,
                MessageOutbox.source_type == "onboarding_probe",
                MessageOutbox.deleted_at.is_(None),
            )
            .order_by(MessageOutbox.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if probe_outbox is not None:
        if str(probe_outbox.status or "").lower() in {"sent", "sending", "pending"}:
            can_send_test_message = True
        if probe_outbox.provider_message_id:
            status_evt = (
                await db.execute(
                    select(ProviderWebhookEvent)
                    .where(
                        ProviderWebhookEvent.business_id == business.id,
                        ProviderWebhookEvent.deleted_at.is_(None),
                    )
                    .order_by(ProviderWebhookEvent.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            # treat presence of any processed provider webhook after probe as receive capability evidence
            if status_evt is not None and status_evt.processing_status == "processed":
                can_receive_webhook = True
    if webhook_last_received_at and webhook_last_received_at >= (now - timedelta(hours=24)):
        can_receive_webhook = True

    all_green = all(
        [
            embedded_signup_completed,
            code_exchanged,
            token_valid,
            required_scopes_granted,
            business_fetch_ok,
            waba_fetch_ok,
            phone_fetch_ok,
            phone_belongs_to_waba,
            waba_subscribed_to_app,
            messages_webhook_enabled,
            phone_registered,
            can_send_test_message,
            can_receive_webhook,
            templates_fetch_ok,
        ]
    )
    any_started = embedded_signup_completed or code_exchanged or (waba is not None) or (phone is not None)
    if all_green:
        final_status = "operational"
    elif not any_started:
        final_status = "not_started"
    elif token_valid and required_scopes_granted and (waba is not None) and (phone is not None):
        final_status = "pending"
    else:
        final_status = "action_required"

    return WhatsAppOperationalReadinessResponse(
        embedded_signup_completed=embedded_signup_completed,
        code_exchanged=code_exchanged,
        token_valid=token_valid,
        required_scopes_granted=required_scopes_granted,
        business_fetch_ok=business_fetch_ok,
        waba_fetch_ok=waba_fetch_ok,
        phone_fetch_ok=phone_fetch_ok,
        phone_belongs_to_waba=phone_belongs_to_waba,
        waba_subscribed_to_app=waba_subscribed_to_app,
        messages_webhook_enabled=messages_webhook_enabled,
        webhook_last_received_at=webhook_last_received_at,
        phone_registered=phone_registered,
        can_send_test_message=can_send_test_message,
        can_receive_webhook=can_receive_webhook,
        templates_fetch_ok=templates_fetch_ok,
        final_status=final_status,
    )


@router.get("/diagnostics", response_model=WhatsAppDiagnosticsResponse)
async def get_whatsapp_diagnostics(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    readiness = await get_operational_readiness(db=db, actor=actor)
    business = actor.business
    waba = (
        await db.execute(
            select(WhatsAppBusinessAccount)
            .where(
                WhatsAppBusinessAccount.business_id == business.id,
                WhatsAppBusinessAccount.deleted_at.is_(None),
            )
            .order_by(WhatsAppBusinessAccount.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    phone = (
        await db.execute(
            select(WhatsAppPhoneNumber)
            .where(
                WhatsAppPhoneNumber.business_id == business.id,
                WhatsAppPhoneNumber.disconnected_at.is_(None),
                WhatsAppPhoneNumber.deleted_at.is_(None),
            )
            .order_by(WhatsAppPhoneNumber.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    last_inbound = (
        await db.execute(
            select(WebhookEvent.received_at)
            .where(
                WebhookEvent.business_id == business.id,
                WebhookEvent.provider == "whatsapp",
                WebhookEvent.deleted_at.is_(None),
            )
            .order_by(WebhookEvent.received_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return WhatsAppDiagnosticsResponse(
        business_id=business.id,
        waba_id=(waba.waba_id if waba else None),
        phone_number_id=(phone.phone_number_id if phone else None),
        token_valid=readiness.token_valid,
        required_scopes=sorted(list(WHATSAPP_REQUIRED_SCOPES)),
        waba_fetch_ok=readiness.waba_fetch_ok,
        phone_numbers_fetch_ok=readiness.phone_fetch_ok,
        subscribed_apps_ok=readiness.waba_subscribed_to_app,
        messages_webhook_enabled=readiness.messages_webhook_enabled,
        phone_registered=readiness.phone_registered,
        last_webhook_received_at=readiness.webhook_last_received_at,
        last_inbound_message_received_at=last_inbound,
        test_send_result="success" if readiness.can_send_test_message else "not_verified",
    )


@router.get("/onboarding/events", response_model=list[OnboardingEventLogItem])
async def get_onboarding_event_log(
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    rows = (
        await db.execute(
            select(OnboardingEventLedger)
            .where(OnboardingEventLedger.business_id == actor.business.id)
            .order_by(OnboardingEventLedger.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        OnboardingEventLogItem(
            created_at=r.created_at,
            event_type=r.event_type,
            event_status=r.event_status,
            operation_id=r.operation_id,
            waba_id=r.waba_id,
            phone_number_id=r.phone_number_id,
            graph_api_endpoint=r.graph_api_endpoint,
            graph_error_code=r.graph_error_code,
            graph_error_subcode=r.graph_error_subcode,
            fbtrace_id=r.fbtrace_id,
            trace_id=r.trace_id,
            error_message=r.error_message,
        )
        for r in rows
    ]


@router.get("/webhook/inbox-debug", response_model=list[WebhookInboxDebugItem])
async def get_webhook_inbox_debug(
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    rows = (
        await db.execute(
            select(WebhookEvent)
            .where(
                WebhookEvent.business_id == actor.business.id,
                WebhookEvent.provider == "whatsapp",
                WebhookEvent.deleted_at.is_(None),
            )
            .order_by(WebhookEvent.received_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    items: list[WebhookInboxDebugItem] = []
    for evt in rows:
        payload = evt.raw_payload or {}
        entry = (payload.get("entry") or [{}])[0]
        value = ((entry.get("changes") or [{}])[0] or {}).get("value") or {}
        metadata = value.get("metadata") or {}
        messages = value.get("messages") or []
        statuses = value.get("statuses") or []
        direction = "inbound" if messages else ("status" if statuses else None)
        message_id = None
        payload_type = None
        if messages:
            message_id = str((messages[0] or {}).get("id") or "") or None
            payload_type = str((messages[0] or {}).get("type") or "message")
        elif statuses:
            message_id = str((statuses[0] or {}).get("id") or "") or None
            payload_type = "status"
        items.append(
            WebhookInboxDebugItem(
                event_id=evt.event_id,
                waba_id=str(entry.get("id") or "") or None,
                phone_number_id=str(metadata.get("phone_number_id") or "") or None,
                message_id=message_id,
                direction=direction,
                payload_type=payload_type,
                received_at=evt.received_at,
                signature_valid=True,
                processed_status=str(evt.processing_status or "unknown"),
                error=evt.failure_reason,
            )
        )
    return items
    await db.commit()
    return WhatsAppOperationalProjectionResponse(
        business_id=actor.business.id,
        credential_health=projection.credential_health,
        subscription_health=projection.subscription_health,
        phone_readiness=projection.phone_readiness,
        webhook_heartbeat=projection.webhook_heartbeat,
        probe_send=projection.probe_send,
        unified_state=projection.unified_state,
        reason=projection.reason,
    )


@router.get("/setup-diagnostics", response_model=WhatsAppSetupDiagnosticsResponse)
async def get_whatsapp_setup_diagnostics(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    waba_res = await db.execute(
        select(WhatsAppBusinessAccount)
        .where(WhatsAppBusinessAccount.business_id == business.id)
        .order_by(WhatsAppBusinessAccount.created_at.desc())
    )
    waba = waba_res.scalars().first()
    waba_id = waba.waba_id if waba else None

    template_query = select(WhatsAppMessageTemplate).where(
        WhatsAppMessageTemplate.business_id == business.id,
        WhatsAppMessageTemplate.deleted_at.is_(None),
    )
    if waba_id:
        template_query = template_query.where(WhatsAppMessageTemplate.waba_id == waba_id)
    template_rows = (await db.execute(template_query)).scalars().all()
    template_total = len(template_rows)
    template_approved = sum(1 for t in template_rows if str(t.status or "").lower() in {"approved", "active"})
    template_pending = sum(1 for t in template_rows if str(t.status or "").lower() in {"pending", "in_review", "submitted"})
    template_last_synced_at = None
    for t in template_rows:
        ts = t.last_synced_at
        if ts and (template_last_synced_at is None or ts > template_last_synced_at):
            template_last_synced_at = ts
    if template_total == 0:
        template_sync_status = "pending"
    elif template_pending > 0:
        template_sync_status = "in_progress"
    else:
        template_sync_status = "synced"

    subscription_res = await db.execute(
        select(WebhookSubscription)
        .where(
            WebhookSubscription.business_id == business.id,
            WebhookSubscription.provider == "whatsapp",
            WebhookSubscription.deleted_at.is_(None),
        )
        .order_by(WebhookSubscription.created_at.desc())
    )
    subscription = subscription_res.scalars().first()
    webhook_subscription_status = str(subscription.status if subscription else "inactive")
    webhook_last_received_at = subscription.last_webhook_received_at if subscription else None
    heartbeat_status = "inactive"
    lag_seconds: int | None = None
    now = datetime.now(timezone.utc)
    if webhook_subscription_status.lower() == "active" and webhook_last_received_at is not None:
        lag_seconds = int((now - webhook_last_received_at).total_seconds())
        if webhook_last_received_at >= (now - timedelta(minutes=15)):
            heartbeat_status = "healthy"
        elif webhook_last_received_at >= (now - timedelta(hours=2)):
            heartbeat_status = "delayed"
        else:
            heartbeat_status = "inactive"
    elif webhook_subscription_status.lower() == "active":
        heartbeat_status = "awaiting_first_event"

    return WhatsAppSetupDiagnosticsResponse(
        business_id=business.id,
        waba_id=waba_id,
        template_sync_status=template_sync_status,
        template_total_count=template_total,
        template_approved_count=template_approved,
        template_pending_count=template_pending,
        template_last_synced_at=template_last_synced_at,
        webhook_subscription_status=webhook_subscription_status,
        webhook_last_received_at=webhook_last_received_at,
        webhook_heartbeat_status=heartbeat_status,
        webhook_heartbeat_lag_seconds=lag_seconds,
    )


@router.post("/reconnect")
async def reconnect_whatsapp(
    payload: MetaOAuthCallbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    return await connect_whatsapp(payload=payload, request=request, db=db, actor=actor)


@router.post("/onboarding/recover", response_model=EmbeddedSignupSessionCreateResponse)
async def recover_failed_onboarding(
    payload: EmbeddedSignupSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    await db.execute(
        update(OnboardingOperation)
        .where(OnboardingOperation.business_id == actor.business.id, OnboardingOperation.status != "completed")
        .values(status="failed", compensating_action_required=False)
    )
    session_row, raw_state = await EmbeddedSignupService(db).create_session(
        business_id=actor.business.id,
        user_id=actor.user.id,
        expected_origin=payload.expected_origin.strip(),
        ttl_minutes=payload.ttl_minutes,
    )
    db.add(
        OnboardingOperation(
            business_id=actor.business.id,
            operation_id=f"recover_{session_row.id}",
            status=transition_onboarding_state(None, "embedded_signup_session_created").status,
            current_step=transition_onboarding_state(None, "embedded_signup_session_created").current_step,
            compensating_action_required=transition_onboarding_state(None, "embedded_signup_session_created").compensating_action_required,
        )
    )
    await db.commit()
    return EmbeddedSignupSessionCreateResponse(
        onboarding_session_id=session_row.id,
        state=raw_state,
        expected_origin=session_row.expected_origin,
        expires_at=session_row.expires_at,
    )

@router.post("/connect")
async def connect_whatsapp(
    payload: MetaOAuthCallbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect"))
):
    """Stores WhatsApp credentials for the logged-in business via server-side OAuth code exchange."""
    business = actor.business
    audit = AuditLogService(db)
    ledger = OnboardingEventLedgerService(db)
    trace_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
    logger.info(f"Connecting WhatsApp for business {business.id}. Payload: {payload}")
    
    if not payload.code:
        raise HTTPException(status_code=400, detail="OAuth callback code is required")
    if not payload.state or len(payload.state.strip()) < 8:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    state_hash = hash_token(payload.state.strip())
    session_result = await db.execute(
        select(EmbeddedSignupSession).where(
            EmbeddedSignupSession.business_id == business.id,
            EmbeddedSignupSession.user_id == actor.user.id,
            EmbeddedSignupSession.state_hash == state_hash,
            EmbeddedSignupSession.status == "pending",
            EmbeddedSignupSession.expires_at > datetime.now(timezone.utc),
            EmbeddedSignupSession.deleted_at.is_(None),
        ).with_for_update()
    )
    signup_session = session_result.scalar_one_or_none()
    if not signup_session:
        raise HTTPException(status_code=400, detail="Invalid or expired embedded signup session")
    lock_service = OperationLockService(db)
    lock_owner = secrets.token_hex(16)
    lock_name = "whatsapp_onboarding_connect"
    lock_acquired = False
    async def _release_lock_if_needed() -> None:
        nonlocal lock_acquired
        if not lock_acquired:
            return
        try:
            await lock_service.release(business.id, lock_name, lock_owner)
        finally:
            lock_acquired = False
    try:
        await lock_service.acquire(
            business_id=business.id,
            lock_name=lock_name,
            owner_token=lock_owner,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        lock_acquired = True
    except Exception:
        raise HTTPException(status_code=409, detail="Another WhatsApp onboarding operation is already in progress")

    try:
        access_token = None
        waba_id = None
        phone_number_id = None
        permissions_granted: list[str] = []
        token_expires_at = None
        waba_profile: dict = {}
        phone_profile: dict = {}
        app_id = settings.META_APP_ID or settings.FB_APP_ID
        app_secret = settings.META_APP_SECRET or settings.FB_APP_SECRET
        if not app_id or not app_secret:
            logger.error("Facebook App credentials missing")
            await audit.write(
                action="whatsapp.connect",
                resource_type="whatsapp_business_account",
                status="failed",
                business_id=business.id,
                user_id=actor.user.id,
                actor_type="user",
                actor_id=str(actor.user.id),
                resource_id=str(business.id),
                details={"reason": "missing_facebook_app_credentials"},
            )
            await ledger.append(
                business_id=business.id,
                operation_id=f"onboard_{signup_session.id}",
                event_type="connect_failed_missing_app_credentials",
                event_status="failed",
                merchant_user_id=actor.user.id,
                trace_id=trace_id,
                error_message="Facebook App credentials not configured on server",
            )
            raise HTTPException(status_code=500, detail="Facebook App credentials not configured on server")
    
        try:
            async with httpx.AsyncClient() as client:
                token_url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/oauth/access_token"
                params = {
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "code": payload.code,
                }
                logger.info(f"Exchanging code for token at {token_url}")
                resp = await client.get(token_url, params=params)
                if resp.status_code != 200:
                    logger.error(f"Failed to exchange code: {resp.text}")
                    await ledger.append(
                        business_id=business.id,
                        operation_id=f"onboard_{signup_session.id}",
                        event_type="oauth_code_exchange_failed",
                        event_status="failed",
                        merchant_user_id=actor.user.id,
                        meta_app_id=str(app_id),
                        graph_api_endpoint=token_url,
                        trace_id=trace_id,
                        error_message=resp.text,
                    )
                    raise HTTPException(status_code=400, detail=f"Failed to exchange Facebook code: {resp.text}")
    
                data = resp.json()
                logger.info("Exchange response received from Meta OAuth endpoint")
                access_token = data.get("access_token")
                logger.info("Access token obtained successfully")
                if not access_token:
                    await ledger.append(
                        business_id=business.id,
                        operation_id=f"onboard_{signup_session.id}",
                        event_type="oauth_code_exchange_empty_token",
                        event_status="failed",
                        merchant_user_id=actor.user.id,
                        meta_app_id=str(app_id),
                        graph_api_endpoint=token_url,
                        trace_id=trace_id,
                    )
                    raise HTTPException(status_code=400, detail="Meta OAuth exchange returned empty access token")
                # Exchange for a longer-lived user token where supported.
                long_lived_url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/oauth/access_token"
                long_lived_params = {
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": access_token,
                }
                long_lived_resp = await client.get(long_lived_url, params=long_lived_params)
                if long_lived_resp.status_code == 200:
                    ll_payload = long_lived_resp.json() or {}
                    exchanged = str(ll_payload.get("access_token") or "").strip()
                    if exchanged:
                        access_token = exchanged
                        if ll_payload.get("expires_in"):
                            try:
                                token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(ll_payload.get("expires_in")))
                            except Exception:
                                pass
                elif bool(settings.META_REQUIRE_LONG_LIVED_TOKEN):
                    await ledger.append(
                        business_id=business.id,
                        operation_id=f"onboard_{signup_session.id}",
                        event_type="long_lived_token_exchange_failed",
                        event_status="failed",
                        merchant_user_id=actor.user.id,
                        meta_app_id=str(app_id),
                        graph_api_endpoint=long_lived_url,
                        trace_id=trace_id,
                        error_message=long_lived_resp.text,
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=f"Failed long-lived token exchange: {long_lived_resp.text}",
                    )
    
                debug_url = "https://graph.facebook.com/debug_token"
                debug_params = {
                    "input_token": access_token,
                    "access_token": f"{app_id}|{app_secret}",
                }
                debug_resp = await client.get(debug_url, params=debug_params)
                debug_json = debug_resp.json()
                debug_data = debug_json.get("data") or {}
                logger.info("Debug token response received")
                if not debug_data.get("is_valid"):
                    raise HTTPException(status_code=400, detail="Meta token is invalid")
                token_expires_unix = debug_data.get("expires_at")
                if token_expires_unix and int(token_expires_unix) > 0:
                    token_expires_at = datetime.fromtimestamp(int(token_expires_unix), tz=timezone.utc)
                raw_scopes = debug_data.get("scopes") or debug_data.get("granular_scopes") or []
                if raw_scopes and isinstance(raw_scopes, list):
                    permissions_granted = [
                        s.get("scope") if isinstance(s, dict) else str(s)
                        for s in raw_scopes
                    ]
                    permissions_granted = [p for p in permissions_granted if p]
                app_id_from_token = str(debug_data.get("app_id") or "")
                if app_id and app_id_from_token and app_id_from_token != str(app_id):
                    await ledger.append(
                        business_id=business.id,
                        operation_id=f"onboard_{signup_session.id}",
                        event_type="token_app_mismatch",
                        event_status="failed",
                        merchant_user_id=actor.user.id,
                        meta_app_id=str(app_id),
                        trace_id=trace_id,
                        graph_response_json=debug_json,
                    )
                    raise HTTPException(status_code=400, detail="Token app mismatch")
    
                if not waba_id:
                    logger.info("WABA ID not in payload, attempting discovery...")
                    waba_url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/me/whatsapp_business_accounts"
                    try:
                        waba_resp = await client.get(waba_url, params={"access_token": access_token})
                        waba_data = waba_resp.json()
                        logger.info(f"Discovery Try 1 (/me/whatsapp_business_accounts): {waba_data}")
                        if waba_data.get("data"):
                            waba_id = waba_data["data"][0]["id"]
                            logger.info(f"Discovery Success via Try 1: {waba_id}")
                    except Exception as e:
                        logger.error(f"Discovery Try 1 failed: {e}")
    
                if not waba_id:
                    me_url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/me"
                    try:
                        me_resp = await client.get(me_url, params={"fields": "whatsapp_business_accounts", "access_token": access_token})
                        me_data = me_resp.json()
                        logger.info(f"Discovery Try 2 (/me?fields=...): {me_data}")
                        wabas = me_data.get("whatsapp_business_accounts", {}).get("data", [])
                        if wabas:
                            waba_id = wabas[0]["id"]
                            logger.info(f"Discovery Success via Try 2: {waba_id}")
                    except Exception as e:
                        logger.error(f"Discovery Try 2 failed: {e}")
        except HTTPException:
            signup_session.status = "failed"
            signup_session.failed_at = datetime.now(timezone.utc)
            signup_session.failure_reason = "oauth_exchange_or_validation_failed"
            await db.commit()
            raise
        except Exception:
            signup_session.status = "failed"
            signup_session.failed_at = datetime.now(timezone.utc)
            signup_session.failure_reason = "unexpected_oauth_error"
            await db.commit()
            raise
        
        if not access_token or not waba_id:
            logger.error(f"Final Missing credentials: access_token={'present' if access_token else 'missing'}, waba_id={'present' if waba_id else 'missing'}")
            await audit.write(
                action="whatsapp.connect",
                resource_type="whatsapp_business_account",
                status="failed",
                business_id=business.id,
                user_id=actor.user.id,
                actor_type="user",
                actor_id=str(actor.user.id),
                resource_id=str(business.id),
                details={"reason": "missing_access_token_or_waba_id"},
            )
            await ledger.append(
                business_id=business.id,
                operation_id=f"onboard_{signup_session.id}",
                event_type="missing_access_token_or_waba_id",
                event_status="failed",
                merchant_user_id=actor.user.id,
                meta_app_id=str(app_id),
                trace_id=trace_id,
            )
            raise HTTPException(
                status_code=400, 
                detail={
                    "message": "Missing access_token or waba_id after discovery",
                    "waba_id_found": waba_id is not None,
                    "access_token_found": access_token is not None
                }
            )
        granted_scope_set = {str(scope).strip() for scope in permissions_granted if str(scope).strip()}
        missing_required_scopes = _missing_required_scopes(permissions_granted)
        if missing_required_scopes:
            metrics.increment(
                "whatsapp_connect_missing_scope_total",
                tags={"missing_scope_count": len(missing_required_scopes)},
            )
            signup_session.status = "failed"
            signup_session.failed_at = datetime.now(timezone.utc)
            signup_session.failure_reason = "missing_required_scopes"
            await db.commit()
            await audit.write(
                action="whatsapp.connect",
                resource_type="whatsapp_business_account",
                status="failed",
                business_id=business.id,
                user_id=actor.user.id,
                actor_type="user",
                actor_id=str(actor.user.id),
                resource_id=str(waba_id),
                details={
                    "reason": "missing_required_scopes",
                    "missing_scopes": missing_required_scopes,
                    "granted_scopes": sorted(granted_scope_set),
                    "trace_id": trace_id,
                },
            )
            await ledger.append(
                business_id=business.id,
                operation_id=f"onboard_{signup_session.id}",
                event_type="missing_required_scopes",
                event_status="failed",
                merchant_user_id=actor.user.id,
                waba_id=str(waba_id) if waba_id else None,
                meta_app_id=str(app_id),
                trace_id=trace_id,
                graph_response_json={"granted_scopes": sorted(granted_scope_set), "missing_scopes": missing_required_scopes},
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Missing required WhatsApp scopes",
                    "missing_scopes": missing_required_scopes,
                },
            )
        # Validate token-to-asset ownership by resolving the WABA directly via Graph with the same token.
        try:
            waba_validation_url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{waba_id}"
            async with httpx.AsyncClient() as client:
                waba_validation_resp = await client.get(
                    waba_validation_url,
                    params={
                        "fields": "id",
                        "access_token": access_token,
                    },
                )
                waba_validation_resp.raise_for_status()
                waba_validation_payload = waba_validation_resp.json()
            resolved_waba_id = str(waba_validation_payload.get("id") or "")
            if resolved_waba_id != str(waba_id):
                signup_session.status = "failed"
                signup_session.failed_at = datetime.now(timezone.utc)
                signup_session.failure_reason = "waba_token_ownership_mismatch"
                await db.commit()
                await audit.write(
                    action="whatsapp.connect",
                    resource_type="whatsapp_business_account",
                    status="failed",
                    business_id=business.id,
                    user_id=actor.user.id,
                    actor_type="user",
                    actor_id=str(actor.user.id),
                    resource_id=str(waba_id),
                    details={
                        "reason": "resolved_waba_id_mismatch",
                        "resolved_waba_id": resolved_waba_id,
                    },
                )
                raise HTTPException(status_code=400, detail="Token cannot access the selected WABA")
        except HTTPException:
            raise
        except Exception as e:
            signup_session.status = "failed"
            signup_session.failed_at = datetime.now(timezone.utc)
            signup_session.failure_reason = "waba_token_ownership_validation_failed"
            await db.commit()
            await audit.write(
                action="whatsapp.connect",
                resource_type="whatsapp_business_account",
                status="failed",
                business_id=business.id,
                user_id=actor.user.id,
                actor_type="user",
                actor_id=str(actor.user.id),
                resource_id=str(waba_id),
                details={
                    "reason": "waba_ownership_validation_request_failed",
                    "error": str(e),
                },
            )
            raise HTTPException(status_code=502, detail="Unable to validate token ownership for selected WABA")
    
        # Fetch phone number ID automatically if not provided
        if not phone_number_id:
            logger.info(f"Phone number ID not in payload, fetching for WABA {waba_id}")
            try:
                phone_number_id = await whatsapp_service.get_phone_number_id(waba_id, access_token)
                logger.info(f"Fetched phone_number_id: {phone_number_id}")
            except Exception as e:
                logger.error(f"Failed to fetch phone number ID: {e}")
        try:
            waba_profile = await whatsapp_service.get_waba_profile(waba_id=waba_id, token=access_token)
        except Exception as e:
            logger.warning(f"Failed to fetch WABA profile: {e}")
        if not phone_number_id:
            signup_session.status = "failed"
            signup_session.failed_at = datetime.now(timezone.utc)
            signup_session.failure_reason = "missing_phone_number_id"
            await db.commit()
            await audit.write(
                action="whatsapp.connect",
                resource_type="whatsapp_phone_number",
                status="failed",
                business_id=business.id,
                user_id=actor.user.id,
                actor_type="user",
                actor_id=str(actor.user.id),
                resource_id=str(waba_id),
                details={"reason": "missing_phone_number_id_after_discovery"},
            )
            await ledger.append(
                business_id=business.id,
                operation_id=f"onboard_{signup_session.id}",
                event_type="missing_phone_number_id_after_discovery",
                event_status="failed",
                merchant_user_id=actor.user.id,
                waba_id=str(waba_id) if waba_id else None,
                meta_app_id=str(app_id),
                trace_id=trace_id,
            )
            raise HTTPException(status_code=400, detail="Phone number ID is required for provisioning")
        if phone_number_id:
            try:
                # Validate that the selected phone_number_id actually belongs to the same WABA.
                numbers_url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{waba_id}/phone_numbers"
                async with httpx.AsyncClient() as client:
                    numbers_resp = await client.get(numbers_url, params={"access_token": access_token})
                    numbers_resp.raise_for_status()
                    numbers_data = numbers_resp.json()
                waba_phone_ids = {
                    str((row or {}).get("id") or "")
                    for row in (numbers_data.get("data") or [])
                    if (row or {}).get("id")
                }
                if str(phone_number_id) not in waba_phone_ids:
                    signup_session.status = "failed"
                    signup_session.failed_at = datetime.now(timezone.utc)
                    signup_session.failure_reason = "phone_not_in_waba"
                    await db.commit()
                    await audit.write(
                        action="whatsapp.connect",
                        resource_type="whatsapp_phone_number",
                        status="failed",
                        business_id=business.id,
                        user_id=actor.user.id,
                        actor_type="user",
                        actor_id=str(actor.user.id),
                        resource_id=str(phone_number_id),
                        details={"reason": "phone_number_not_in_waba", "waba_id": str(waba_id)},
                    )
                    raise HTTPException(status_code=400, detail="Phone number does not belong to selected WABA")
                phone_profile = await whatsapp_service.get_phone_number_profile(phone_number_id=phone_number_id, token=access_token)
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Failed to validate/fetch phone profile: {e}")
        subscribed_fields: list[str] = []
        try:
            subscription_result = await waba_subscription_service.ensure_subscribed(
                waba_id=waba_id,
                access_token=access_token,
                app_id=str(app_id),
            )
            subscribed_fields = subscription_result.subscribed_fields
            if not _has_messages_field(subscribed_fields):
                metrics.increment("whatsapp_subscription_missing_messages_field_total")
                signup_session.status = "failed"
                signup_session.failed_at = datetime.now(timezone.utc)
                signup_session.failure_reason = "messages_field_not_subscribed"
                await db.commit()
                await audit.write(
                    action="whatsapp.subscription.register",
                    resource_type="whatsapp_business_account",
                    status="failed",
                    business_id=business.id,
                    user_id=actor.user.id,
                    actor_type="user",
                    actor_id=str(actor.user.id),
                    resource_id=waba_id,
                    details={
                        "reason": "messages_field_not_subscribed",
                        "subscribed_fields": subscribed_fields,
                        "trace_id": trace_id,
                    },
                )
                raise HTTPException(
                    status_code=400,
                    detail="App is subscribed to WABA but missing required 'messages' webhook field in Meta app configuration",
                )
        except WabaSubscriptionServiceError as exc:
            metrics.increment(
                "whatsapp_subscription_failure_total",
                tags={
                    "graph_error_code": str(exc.error_code or "unknown"),
                    "graph_error_subcode": str(exc.error_subcode or "unknown"),
                },
            )
            signup_session.status = "failed"
            signup_session.failed_at = datetime.now(timezone.utc)
            signup_session.failure_reason = "waba_subscription_failed"
            await db.commit()
            await audit.write(
                action="whatsapp.subscription.register",
                resource_type="whatsapp_business_account",
                status="failed",
                business_id=business.id,
                user_id=actor.user.id,
                actor_type="user",
                actor_id=str(actor.user.id),
                resource_id=waba_id,
                details={
                    "status_code": exc.status_code,
                    "response_body": exc.response_body,
                    "graph_error_code": exc.error_code,
                    "graph_error_subcode": exc.error_subcode,
                    "graph_fbtrace_id": exc.fbtrace_id,
                    "trace_id": trace_id,
                },
            )
            await ledger.append(
                business_id=business.id,
                operation_id=f"onboard_{signup_session.id}",
                event_type="waba_subscription_failed",
                event_status="failed",
                merchant_user_id=actor.user.id,
                waba_id=str(waba_id) if waba_id else None,
                meta_app_id=str(app_id),
                graph_api_endpoint=f"/{settings.META_GRAPH_API_VERSION}/{waba_id}/subscribed_apps",
                graph_error_code=str(exc.error_code) if exc.error_code is not None else None,
                graph_error_subcode=str(exc.error_subcode) if exc.error_subcode is not None else None,
                fbtrace_id=exc.fbtrace_id,
                trace_id=trace_id,
                error_message=str(exc),
            )
            raise HTTPException(status_code=502, detail="Failed to register app subscription on WABA")
    
        logger.info(f"Final credentials for business {business.id}: WABA={waba_id}, Phone={phone_number_id}")
        verify_token = secrets.token_hex(16)
        async with db.begin():
            await db.execute(
                delete(WebhookSubscription).where(
                    WebhookSubscription.business_id == business.id,
                    WebhookSubscription.provider == "whatsapp",
                )
            )
            await db.execute(
                delete(OAuthCredential).where(
                    OAuthCredential.business_id == business.id,
                    OAuthCredential.provider == "whatsapp",
                )
            )
            await db.execute(
                delete(WhatsAppBusinessAccount).where(WhatsAppBusinessAccount.business_id == business.id)
            )
            await db.execute(
                delete(MetaBusinessAccount).where(MetaBusinessAccount.business_id == business.id)
            )
    
            oauth = await OAuthCredentialRepository(db).store_encrypted_access_token(
                business_id=business.id,
                provider="whatsapp",
                access_token=access_token,
                credential_owner_type="business",
                credential_owner_id=str(business.id),
                scopes=permissions_granted,
            )
            oauth.expires_at = token_expires_at
            oauth.grant_type = "fb_exchange_token"
            oauth.provider_subject_id = str((waba_id or "").strip() or business.id)
    
            meta = MetaBusinessAccount(
                business_id=business.id,
                meta_business_account_id=waba_id,
            )
            db.add(meta)
            await db.flush()
    
            waba = WhatsAppBusinessAccount(
                business_id=business.id,
                waba_id=waba_id,
                display_name=waba_profile.get("name"),
                currency=waba_profile.get("currency"),
                timezone=str(waba_profile.get("timezone")) if waba_profile.get("timezone") is not None else None,
            )
            db.add(waba)
            await db.flush()
            waba_asset = ProviderAsset(
                provider="meta",
                external_id=waba_id,
                business_id=business.id,
                asset_type="whatsapp_business_account",
                metadata_json={},
            )
            db.add(waba_asset)
            await db.flush()
            db.add(
                BusinessProviderAssetLink(
                    business_id=business.id,
                    provider_asset_id=waba_asset.id,
                    link_status="linked",
                    verified_at=func.now(),
                    verification_method="embedded_signup",
                    verified_by_credential_id=oauth.id,
                )
            )
    
            if phone_number_id:
                db.add(
                    WhatsAppPhoneNumber(
                        business_id=business.id,
                        phone_number_id=phone_number_id,
                        display_phone_number=phone_profile.get("display_phone_number"),
                        verified_name=phone_profile.get("verified_name"),
                        quality_rating=phone_profile.get("quality_rating"),
                        messaging_limit_tier=phone_profile.get("messaging_limit_tier"),
                        verification_status=phone_profile.get("code_verification_status"),
                        environment="live",
                    )
                )
                phone_asset = ProviderAsset(
                    provider="meta",
                    external_id=phone_number_id,
                    business_id=business.id,
                    asset_type="whatsapp_phone_number",
                    metadata_json={"waba_id": waba_id},
                )
                db.add(phone_asset)
                await db.flush()
                db.add(
                    BusinessProviderAssetLink(
                        business_id=business.id,
                        provider_asset_id=phone_asset.id,
                        link_status="linked",
                        verified_at=func.now(),
                        verification_method="embedded_signup",
                        verified_by_credential_id=oauth.id,
                    )
                )
    
            await WebhookSecretRepository(db).create_hashed_secret(
                business_id=business.id,
                provider="whatsapp",
                verify_token=verify_token,
                waba_id=waba_id,
                phone_number_id=phone_number_id,
                status="active",
                subscribed_fields=subscribed_fields,
                environment="live",
            )
            existing_integration = await db.execute(
                select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == business.id)
            )
            integration = existing_integration.scalar_one_or_none()
            if integration:
                integration.status = transition_whatsapp_integration_status(integration.status, "provisioning")
                integration.disconnected_at = None
            else:
                db.add(WhatsAppIntegration(business_id=business.id, status="provisioning"))
            integration_row = await db.execute(
                select(ProviderIntegration).where(
                    ProviderIntegration.business_id == business.id,
                    ProviderIntegration.provider == "meta",
                    ProviderIntegration.deleted_at.is_(None),
                )
            )
            provider_integration = integration_row.scalar_one_or_none()
            graph_version = settings.META_GRAPH_API_VERSION or "v21.0"
            if provider_integration:
                provider_integration.api_version = graph_version
                provider_integration.status = "active"
            else:
                db.add(
                    ProviderIntegration(
                        business_id=business.id,
                        provider="meta",
                        api_version=graph_version,
                        status="active",
                    )
                )
            db.add(
                WhatsAppAssetConnectionEvent(
                    business_id=business.id,
                    asset_type="waba",
                    asset_id=waba_id,
                    event_type="connected",
                    actor_user_id=actor.user.id,
                    meta_business_id=waba_id,
                )
            )
            if phone_number_id:
                db.add(
                    WhatsAppAssetConnectionEvent(
                        business_id=business.id,
                        asset_type="phone_number",
                        asset_id=phone_number_id,
                        event_type="connected",
                        actor_user_id=actor.user.id,
                        meta_business_id=waba_id,
                    )
                )
            onboarding_operation_id = f"onboard_{signup_session.id}"
            db.add(
                OnboardingOperation(
                    business_id=business.id,
                    operation_id=onboarding_operation_id,
                    status=transition_onboarding_state("oauth_code_received", "phone_registration_queued").status,
                    current_step=transition_onboarding_state("oauth_code_received", "phone_registration_queued").current_step,
                    compensating_action_required=transition_onboarding_state("oauth_code_received", "phone_registration_queued").compensating_action_required,
                )
            )
            db.add(
                OutboxEvent(
                    business_id=business.id,
                    operation_id=onboarding_operation_id,
                    event_type="whatsapp.phone.register",
                    queue_region=str(business.data_region or "global"),
                    queue_domain=classify_outbox_event("whatsapp.phone.register")[0],
                    workload_class=classify_outbox_event("whatsapp.phone.register")[1],
                    trace_id=trace_id,
                    payload_json={
                        "business_id": str(business.id),
                        "waba_id": str(waba_id),
                        "phone_number_id": str(phone_number_id or ""),
                        "onboarding_operation_id": onboarding_operation_id,
                        "onboarding_session_id": str(signup_session.id),
                    },
                    status="pending",
                )
            )
            signup_session.status = "pending"
            signup_session.received_code_at = datetime.now(timezone.utc)
            signup_session.completed_at = None
        await audit.write(
            action="whatsapp.connect",
            resource_type="whatsapp_business_account",
            business_id=business.id,
            user_id=actor.user.id,
            actor_type="user",
            actor_id=str(actor.user.id),
            resource_id=waba_id,
            details={"phone_number_id": phone_number_id},
        )
        await audit.write(
            action="whatsapp.subscription.register",
            resource_type="whatsapp_business_account",
            status="success",
            business_id=business.id,
            user_id=actor.user.id,
            actor_type="user",
            actor_id=str(actor.user.id),
            resource_id=waba_id,
            details={"subscribed_fields": subscribed_fields},
        )
        await ledger.append(
            business_id=business.id,
            operation_id=f"onboard_{signup_session.id}",
            event_type="onboarding_connect_provisioning_queued",
            event_status="success",
            merchant_user_id=actor.user.id,
            waba_id=str(waba_id),
            phone_number_id=str(phone_number_id or ""),
            meta_app_id=str(app_id),
            graph_api_endpoint=f"/{settings.META_GRAPH_API_VERSION}/{waba_id}/subscribed_apps",
            trace_id=trace_id,
            graph_response_json={"subscribed_fields": subscribed_fields},
        )
        return {"status": "provisioning", "phone_number_id": phone_number_id, "verify_token": verify_token, "permissions_granted": permissions_granted, "token_expires_at": token_expires_at}
    
    
    finally:
        await _release_lock_if_needed()

@router.post("/disconnect")
async def disconnect_whatsapp(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    audit = AuditLogService(db)

    integration_row = await db.execute(
        select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == business.id).limit(1)
    )
    integration = integration_row.scalar_one_or_none()
    if integration is not None:
        integration.status = transition_whatsapp_integration_status(integration.status, "disconnecting")
    campaign_state = CampaignStateService(db)
    campaigns = (
        await db.execute(
            select(Campaign).where(
                Campaign.business_id == business.id,
                Campaign.environment == "live",
                Campaign.deleted_at.is_(None),
                Campaign.status.in_(["draft", "validating", "ready", "scheduled", "queued", "running", "paused"]),
            )
        )
    ).scalars().all()
    for campaign in campaigns:
        await campaign_state.transition_campaign(
            business_id=business.id,
            campaign_id=campaign.id,
            new_status="cancelled",
            reason="whatsapp_disconnected",
        )
    await db.execute(
        update(WhatsAppPhoneNumber)
        .where(WhatsAppPhoneNumber.business_id == business.id, WhatsAppPhoneNumber.environment == "live")
        .values(sending_status="disabled", disconnected_at=func.now())
    )
    await db.execute(
        update(OAuthCredential)
        .where(OAuthCredential.business_id == business.id, OAuthCredential.provider == "whatsapp", OAuthCredential.environment == "live")
        .values(revoked_at=func.now())
    )
    await db.execute(
        update(WebhookSubscription)
        .where(WebhookSubscription.business_id == business.id, WebhookSubscription.provider == "whatsapp", WebhookSubscription.environment == "live")
        .values(status="inactive")
    )
    if integration is not None:
        integration.status = transition_whatsapp_integration_status(integration.status, "disconnected")
        integration.disconnected_at = datetime.now(timezone.utc)
    db.add(
        WhatsAppAssetConnectionEvent(
            business_id=business.id,
            asset_type="integration",
            asset_id=str(business.id),
            event_type="disconnected",
            actor_user_id=actor.user.id,
        )
    )
    await db.commit()
    await audit.write(
        action="whatsapp.disconnect",
        resource_type="whatsapp_integration",
        business_id=business.id,
        user_id=actor.user.id,
        actor_type="user",
        actor_id=str(actor.user.id),
        resource_id=str(business.id),
    )
    return {"status": "disconnected"}

@router.get("/webhook")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    challenge: str = Query(None, alias="hub.challenge"),
    token: str = Query(None, alias="hub.verify_token"),
):
    """Verification endpoint for WhatsApp Webhook."""
    # Check global token or any business token
    if mode == "subscribe":
        verify_token = settings.META_WEBHOOK_VERIFY_TOKEN or settings.WHATSAPP_VERIFY_TOKEN
        if token == verify_token:
            return PlainTextResponse(content=str(challenge or ""), status_code=200)
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            repo = BusinessRepository(db)
            subscription = await repo.get_webhook_subscription_by_token("whatsapp", token or "")
            if subscription:
                return PlainTextResponse(content=str(challenge or ""), status_code=200)
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/webhook")
async def receive_whatsapp_message(request: Request, db: AsyncSession = Depends(get_db)):
    """Receives notifications from WhatsApp."""
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    app_secret = settings.META_APP_SECRET or settings.FB_APP_SECRET
    env = (settings.APP_ENV or "").strip().lower()
    is_local_env = env in {"local", "dev", "development", "test"}
    if not is_local_env and not app_secret:
        raise HTTPException(status_code=500, detail="Webhook signature secret is not configured for non-local environment")
    if not is_local_env and not signature:
        metrics.increment("whatsapp_webhook_signature_failure_total", tags={"reason": "missing_signature"})
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    if app_secret:
        expected = "sha256=" + hmac.new(
            app_secret.encode("utf-8"), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            metrics.increment("whatsapp_webhook_signature_failure_total", tags={"reason": "invalid_signature"})
            await AuditLogService(db).write(
                action="whatsapp.webhook.receive",
                resource_type="webhook_event",
                status="failed",
                actor_type="system",
                details={"reason": "invalid_signature"},
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        metrics.increment("whatsapp_webhook_parse_failure_total")
        await AuditLogService(db).write(
            action="whatsapp.webhook.receive",
            resource_type="webhook_event",
            status="failed",
            actor_type="system",
            details={"reason": "invalid_json_payload"},
        )
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    logger.info(f"Received WhatsApp data: {data}")

    business_id = None
    channel_id = None
    queue_region = "global"
    if data.get("object") == "whatsapp_business_account":
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})
        waba_id = entry.get("id")
        phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
        if waba_id and phone_number_id:
            try:
                await db.execute(
                    update(WebhookSubscription)
                    .where(
                        WebhookSubscription.provider == "whatsapp",
                        WebhookSubscription.waba_id == str(waba_id),
                        WebhookSubscription.phone_number_id == str(phone_number_id),
                        WebhookSubscription.deleted_at.is_(None),
                    )
                    .values(
                        status="active",
                        last_webhook_received_at=func.now(),
                        last_health_check_at=func.now(),
                        last_health_status="healthy",
                        last_health_error_code=None,
                    )
                )
                business, resolved_channel_id = await WebhookTenantResolver(db).resolve(
                    waba_id=waba_id,
                    phone_number_id=phone_number_id,
                )
                business_id = business.id
                channel_id = resolved_channel_id
                queue_region = str(getattr(business, "data_region", None) or "global")
            except HTTPException as exc:
                logger.warning(
                    "webhook_tenant_resolution_failed waba_id=%s phone_number_id=%s status=%s detail=%s",
                    str(waba_id),
                    str(phone_number_id),
                    str(exc.status_code),
                    str(exc.detail),
                )

    event_type, dedupe_key, provider_event_id = _derive_whatsapp_webhook_identity(data, raw)
    payload_hash = hashlib.sha256(raw).hexdigest()
    webhook_repo = WebhookEventRepository(db)
    webhook_event, created = await webhook_repo.insert_once(
        business_id=business_id,
        provider="whatsapp",
        event_id=dedupe_key,
        payload_hash=payload_hash,
        raw_payload={
            **data,
            "_event_meta": {
                "event_type": event_type,
                "provider_event_id": provider_event_id,
                "dedupe_key": dedupe_key,
            },
        },
        processing_status="pending",
    )
    if not created:
        return {"status": "accepted", "duplicate": True}
    provider_webhook_event = ProviderWebhookEvent(
        business_id=business_id,
        provider="meta",
        event_id=provider_event_id or dedupe_key,
        payload_hash=payload_hash,
        raw_payload={
            **data,
            "_event_meta": {
                "event_type": event_type,
                "provider_event_id": provider_event_id,
                "dedupe_key": dedupe_key,
            },
        },
        processing_status="pending",
    )
    db.add(provider_webhook_event)
    await db.flush()
    db.add(
        OutboxEvent(
            business_id=business_id,
            operation_id=provider_webhook_event.event_id,
            event_type="webhook.process.whatsapp",
            queue_region=queue_region,
            queue_domain=classify_outbox_event("webhook.process.whatsapp")[0],
            workload_class=classify_outbox_event("webhook.process.whatsapp")[1],
            payload_json={
                "webhook_event_id": str(webhook_event.id),
                "channel_id": channel_id,
                "provider": "whatsapp",
            },
            status="pending",
        )
    )
    await db.commit()
    return {"status": "accepted"}


@webhook_alias_router.get("/webhook")
async def verify_webhook_alias(
    mode: str = Query(None, alias="hub.mode"),
    challenge: str = Query(None, alias="hub.challenge"),
    token: str = Query(None, alias="hub.verify_token"),
):
    # Compatibility alias for Meta callback misconfiguration.
    return await verify_webhook(mode=mode, challenge=challenge, token=token)


@webhook_alias_router.post("/webhook")
async def receive_whatsapp_message_alias(request: Request, db: AsyncSession = Depends(get_db)):
    # Compatibility alias for Meta callback misconfiguration.
    return await receive_whatsapp_message(request=request, db=db)


@router.get("/onboarding/debug", response_model=WhatsAppOnboardingDebugResponse)
async def get_whatsapp_onboarding_debug(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    operation_row = await db.execute(
        select(OnboardingOperation)
        .where(OnboardingOperation.business_id == business.id)
        .order_by(OnboardingOperation.created_at.desc())
        .limit(1)
    )
    operation = operation_row.scalars().first()
    attempts = await db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.business_id == business.id,
            OutboxEvent.event_type == "whatsapp.phone.register",
            OutboxEvent.deleted_at.is_(None),
        )
        .order_by(OutboxEvent.created_at.desc())
        .limit(20)
    )
    integration_row = await db.execute(
        select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == business.id).limit(1)
    )
    integration = integration_row.scalar_one_or_none()
    credential_row = await db.execute(
        select(OAuthCredential)
        .where(
            OAuthCredential.business_id == business.id,
            OAuthCredential.provider == "whatsapp",
            OAuthCredential.environment == "live",
        )
        .order_by(OAuthCredential.created_at.desc())
        .limit(1)
    )
    credential = credential_row.scalars().first()
    webhook_row = await db.execute(
        select(WebhookSubscription)
        .where(
            WebhookSubscription.business_id == business.id,
            WebhookSubscription.provider == "whatsapp",
            WebhookSubscription.deleted_at.is_(None),
        )
        .order_by(WebhookSubscription.created_at.desc())
        .limit(1)
    )
    webhook = webhook_row.scalars().first()
    return {
        "integration_status": integration.status if integration else None,
        "onboarding_operation": {
            "operation_id": operation.operation_id if operation else None,
            "status": operation.status if operation else None,
            "current_step": operation.current_step if operation else None,
            "compensating_action_required": operation.compensating_action_required if operation else None,
        },
        "credential": {
            "expires_at": credential.expires_at if credential else None,
            "revoked_at": credential.revoked_at if credential else None,
            "last_health_status": credential.last_health_status if credential else None,
            "last_health_error_code": credential.last_health_error_code if credential else None,
            "scopes": credential.scopes if credential else [],
        },
        "webhook": {
            "status": webhook.status if webhook else None,
            "subscribed_fields": webhook.subscribed_fields if webhook else [],
            "last_webhook_received_at": webhook.last_webhook_received_at if webhook else None,
            "last_health_status": webhook.last_health_status if webhook else None,
            "last_health_error_code": webhook.last_health_error_code if webhook else None,
        },
        "registration_outbox_events": [
            {
                "id": str(evt.id),
                "status": evt.status,
                "attempts": evt.attempts,
                "available_at": evt.available_at,
                "processed_at": evt.processed_at,
                "payload": evt.payload_json,
            }
            for evt in attempts.scalars().all()
        ],
    }

from fastapi import APIRouter, Request, Query, Depends, HTTPException
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
)
import httpx
import secrets
import hmac
import hashlib
import json
from app.core.security import hash_token

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])
logger = logging.getLogger(__name__)


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


@router.get("/onboarding/status", response_model=WhatsAppOnboardingStatusResponse)
async def get_whatsapp_onboarding_status(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    integration_res = await db.execute(
        select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == business.id)
    )
    integration = integration_res.scalar_one_or_none()
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
    return WhatsAppOnboardingStatusResponse(
        integration_status=(integration.status if integration else "disconnected"),
        business_id=business.id,
        waba_id=(waba.waba_id if waba else None),
        phone_number_id=(phone.phone_number_id if phone else None),
        display_phone_number=(phone.display_phone_number if phone else None),
        verified_name=(phone.verified_name if phone else None),
        quality_rating=(phone.quality_rating if phone else None),
        messaging_limit_tier=(phone.messaging_limit_tier if phone else None),
        currency=(waba.currency if waba else None),
        timezone=(waba.timezone if waba else None),
        verification_status=(phone.verification_status if phone else None),
        permissions_granted=(cred.scopes if cred else []),
        token_expires_at=(cred.expires_at if cred else None),
        token_valid=token_valid,
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
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    return await connect_whatsapp(payload=payload, db=db, actor=actor)


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
            status="pending",
            current_step="embedded_signup_session_created",
            compensating_action_required=False,
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
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect"))
):
    """Stores WhatsApp credentials for the logged-in business via server-side OAuth code exchange."""
    business = actor.business
    audit = AuditLogService(db)
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

    access_token = None
    waba_id = payload.waba_id
    phone_number_id = payload.phone_number_id
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
                raise HTTPException(status_code=400, detail=f"Failed to exchange Facebook code: {resp.text}")

            data = resp.json()
            logger.info("Exchange response received from Meta OAuth endpoint")
            access_token = data.get("access_token")
            logger.info("Access token obtained successfully")

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
        raise HTTPException(
            status_code=400, 
            detail={
                "message": "Missing access_token or waba_id after discovery",
                "waba_id_found": waba_id is not None,
                "access_token_found": access_token is not None
            }
        )

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
    if phone_number_id:
        try:
            phone_profile = await whatsapp_service.get_phone_number_profile(phone_number_id=phone_number_id, token=access_token)
        except Exception as e:
            logger.warning(f"Failed to fetch phone profile: {e}")
    
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
            subscribed_fields=[],
            environment="live",
        )
        existing_integration = await db.execute(
            select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == business.id)
        )
        integration = existing_integration.scalar_one_or_none()
        if integration:
            integration.status = "connected"
            integration.disconnected_at = None
        else:
            db.add(WhatsAppIntegration(business_id=business.id, status="connected"))
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
        db.add(
            OnboardingOperation(
                business_id=business.id,
                operation_id=f"onboard_{signup_session.id}",
                status="completed",
                current_step="whatsapp_connected",
                compensating_action_required=False,
            )
        )
        signup_session.status = "completed"
        signup_session.received_code_at = datetime.now(timezone.utc)
        signup_session.completed_at = datetime.now(timezone.utc)
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
    return {"status": "success", "phone_number_id": phone_number_id, "verify_token": verify_token, "permissions_granted": permissions_granted, "token_expires_at": token_expires_at}


@router.post("/disconnect")
async def disconnect_whatsapp(
    db: AsyncSession = Depends(get_db),
    actor: CurrentActor = Depends(require_permissions("whatsapp:connect")),
):
    business = actor.business
    audit = AuditLogService(db)

    await db.execute(
        update(WhatsAppIntegration)
        .where(WhatsAppIntegration.business_id == business.id)
        .values(status="disconnecting")
    )
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
    await db.execute(
        update(WhatsAppIntegration)
        .where(WhatsAppIntegration.business_id == business.id)
        .values(status="disconnected", disconnected_at=func.now())
    )
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
            return int(challenge)
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            repo = BusinessRepository(db)
            subscription = await repo.get_webhook_subscription_by_token("whatsapp", token or "")
            if subscription:
                return int(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/webhook")
async def receive_whatsapp_message(request: Request, db: AsyncSession = Depends(get_db)):
    """Receives notifications from WhatsApp."""
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    app_secret = settings.META_APP_SECRET or settings.FB_APP_SECRET
    is_production = (settings.APP_ENV or "").strip().lower() in {"prod", "production"}
    if is_production and not app_secret:
        raise HTTPException(status_code=500, detail="Webhook signature secret is not configured for production")
    if is_production and not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    if app_secret:
        expected = "sha256=" + hmac.new(
            app_secret.encode("utf-8"), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            await AuditLogService(db).write(
                action="whatsapp.webhook.receive",
                resource_type="webhook_event",
                status="failed",
                actor_type="system",
                details={"reason": "invalid_signature"},
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    data = json.loads(raw.decode("utf-8"))
    logger.info(f"Received WhatsApp data: {data}")

    business_id = None
    channel_id = None
    if data.get("object") == "whatsapp_business_account":
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value", {})
        waba_id = entry.get("id")
        phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
        if waba_id and phone_number_id:
            try:
                business, resolved_channel_id = await WebhookTenantResolver(db).resolve(
                    waba_id=waba_id,
                    phone_number_id=phone_number_id,
                )
                business_id = business.id
                channel_id = resolved_channel_id
            except HTTPException:
                pass

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

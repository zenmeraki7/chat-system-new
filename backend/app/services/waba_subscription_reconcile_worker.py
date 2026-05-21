from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import OAuthCredential, WebhookSubscription, WhatsAppIntegration
from app.services.audit_log_service import AuditLogService
from app.services.token_crypto_service import token_crypto_service
from app.services.waba_subscription_service import (
    WabaSubscriptionServiceError,
    waba_subscription_service,
)
from app.services.observability_metrics import metrics
from app.config import settings
from app.services.whatsapp_integration_state_machine import transition_whatsapp_integration_status
from app.services.onboarding_event_ledger_service import OnboardingEventLedgerService

logger = logging.getLogger(__name__)


class WabaSubscriptionReconcileWorker:
    def __init__(self, *, poll_interval_seconds: float = 300.0, max_batch_size: int = 50) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.max_batch_size = max(1, int(max_batch_size))
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._reconcile_once()
            except Exception:
                logger.exception("waba_subscription_reconcile_loop_failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _reconcile_once(self) -> None:
        app_id = str(settings.META_APP_ID or settings.FB_APP_ID or "").strip()
        if not app_id:
            return
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(WebhookSubscription)
                .where(
                    WebhookSubscription.provider == "whatsapp",
                    WebhookSubscription.deleted_at.is_(None),
                    WebhookSubscription.waba_id.is_not(None),
                )
                .order_by(WebhookSubscription.created_at.asc())
                .limit(self.max_batch_size)
            )
            subscriptions = rows.scalars().all()
            now = datetime.now(timezone.utc)
            for subscription in subscriptions:
                try:
                    cred_row = await db.execute(
                        select(OAuthCredential)
                        .where(
                            OAuthCredential.business_id == subscription.business_id,
                            OAuthCredential.provider == "whatsapp",
                            OAuthCredential.environment == "live",
                            OAuthCredential.revoked_at.is_(None),
                        )
                        .order_by(OAuthCredential.created_at.desc())
                        .limit(1)
                    )
                    credential = cred_row.scalars().first()
                    if credential is None:
                        subscription.status = "inactive"
                        subscription.last_health_check_at = now
                        subscription.last_health_status = "error"
                        subscription.last_health_error_code = "missing_credential"
                        integration_row = await db.execute(
                            select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == subscription.business_id).limit(1)
                        )
                        integration = integration_row.scalar_one_or_none()
                        if integration is not None:
                            integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                        continue
                    token = token_crypto_service.decrypt(credential.access_token_ciphertext)
                    verify = await waba_subscription_service.verify_subscription(
                        waba_id=str(subscription.waba_id),
                        access_token=token,
                        app_id=app_id,
                    )
                    if not verify.app_subscribed:
                        await waba_subscription_service.ensure_subscribed(
                            waba_id=str(subscription.waba_id),
                            access_token=token,
                            app_id=app_id,
                        )
                        verify = await waba_subscription_service.verify_subscription(
                            waba_id=str(subscription.waba_id),
                            access_token=token,
                            app_id=app_id,
                        )
                    if not verify.app_subscribed:
                        raise WabaSubscriptionServiceError("WABA subscription absent after repair attempt")
                    normalized_fields = {
                        str(field).strip().lower()
                        for field in (verify.subscribed_fields or [])
                        if str(field).strip()
                    }
                    if "messages" not in normalized_fields:
                        metrics.increment("whatsapp_subscription_missing_messages_field_total", tags={"source": "reconcile"})
                        raise WabaSubscriptionServiceError("WABA subscription is present but missing messages field")
                    subscription.status = "active"
                    subscription.subscribed_fields = verify.subscribed_fields
                    subscription.last_health_check_at = now
                    subscription.last_health_status = "healthy"
                    subscription.last_health_error_code = None
                    await AuditLogService(db).write(
                        action="whatsapp.subscription.reconcile",
                        resource_type="whatsapp_business_account",
                        status="success",
                        business_id=subscription.business_id,
                        actor_type="system",
                        resource_id=str(subscription.waba_id),
                        details={"subscribed_fields": verify.subscribed_fields},
                    )
                    await OnboardingEventLedgerService(db).append(
                        business_id=subscription.business_id,
                        operation_id=f"reconcile_waba_{subscription.waba_id}",
                        event_type="waba_subscription_reconcile_success",
                        event_status="success",
                        waba_id=str(subscription.waba_id),
                        graph_api_endpoint=f"/{settings.META_GRAPH_API_VERSION}/{subscription.waba_id}/subscribed_apps",
                        graph_response_json={"subscribed_fields": verify.subscribed_fields},
                    )
                except Exception as exc:
                    graph_error_code = str(getattr(exc, "error_code", None) or "unknown")
                    graph_error_subcode = str(getattr(exc, "error_subcode", None) or "unknown")
                    metrics.increment(
                        "whatsapp_subscription_failure_total",
                        tags={
                            "graph_error_code": graph_error_code,
                            "graph_error_subcode": graph_error_subcode,
                        },
                    )
                    subscription.status = "degraded"
                    subscription.last_health_check_at = now
                    subscription.last_health_status = "error"
                    subscription.last_health_error_code = "reconcile_failed"
                    integration_row = await db.execute(
                        select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == subscription.business_id).limit(1)
                    )
                    integration = integration_row.scalar_one_or_none()
                    if integration is not None:
                        integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                    await AuditLogService(db).write(
                        action="whatsapp.subscription.reconcile",
                        resource_type="whatsapp_business_account",
                        status="failed",
                        business_id=subscription.business_id,
                        actor_type="system",
                        resource_id=str(subscription.waba_id),
                        details={"reason": str(exc)},
                    )
                    await OnboardingEventLedgerService(db).append(
                        business_id=subscription.business_id,
                        operation_id=f"reconcile_waba_{subscription.waba_id}",
                        event_type="waba_subscription_reconcile_failed",
                        event_status="failed",
                        waba_id=str(subscription.waba_id),
                        graph_api_endpoint=f"/{settings.META_GRAPH_API_VERSION}/{subscription.waba_id}/subscribed_apps",
                        graph_error_code=graph_error_code if graph_error_code != "unknown" else None,
                        graph_error_subcode=graph_error_subcode if graph_error_subcode != "unknown" else None,
                        error_message=str(exc),
                    )
            await db.commit()

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.business_domains import OAuthCredential, WhatsAppIntegration
from app.services.audit_log_service import AuditLogService
from app.services.token_crypto_service import token_crypto_service
from app.services.whatsapp_integration_state_machine import transition_whatsapp_integration_status
from app.services.onboarding_event_ledger_service import OnboardingEventLedgerService

logger = logging.getLogger(__name__)


class WhatsAppCredentialHealthWorker:
    def __init__(self, *, poll_interval_seconds: float = 300.0, max_batch_size: int = 100) -> None:
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
                logger.exception("whatsapp_credential_health_worker_loop_failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _reconcile_once(self) -> None:
        app_id = str(settings.META_APP_ID or settings.FB_APP_ID or "").strip()
        app_secret = str(settings.META_APP_SECRET or settings.FB_APP_SECRET or "").strip()
        if not app_id or not app_secret:
            return
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            rows = await db.execute(
                select(OAuthCredential)
                .where(
                    OAuthCredential.provider == "whatsapp",
                    OAuthCredential.environment == "live",
                    OAuthCredential.revoked_at.is_(None),
                )
                .order_by(OAuthCredential.created_at.desc())
                .limit(self.max_batch_size)
            )
            credentials = rows.scalars().all()
            for cred in credentials:
                integration_row = await db.execute(
                    select(WhatsAppIntegration)
                    .where(WhatsAppIntegration.business_id == cred.business_id)
                    .limit(1)
                )
                integration = integration_row.scalar_one_or_none()
                if integration is None:
                    continue
                try:
                    if cred.expires_at and cred.expires_at <= now:
                        integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                        cred.last_health_check_at = now
                        cred.last_health_status = "expired"
                        cred.last_health_error_code = "token_expired"
                        await AuditLogService(db).write(
                            action="whatsapp.credential.health",
                            resource_type="oauth_credential",
                            status="failed",
                            business_id=cred.business_id,
                            actor_type="system",
                            resource_id=str(cred.id),
                            details={"reason": "token_expired"},
                        )
                        await OnboardingEventLedgerService(db).append(
                            business_id=cred.business_id,
                            operation_id=f"credential_health_{cred.id}",
                            event_type="credential_expired",
                            event_status="failed",
                            graph_error_code="token_expired",
                            error_message="token expired",
                        )
                        continue
                    token = token_crypto_service.decrypt(cred.access_token_ciphertext)
                    debug_url = "https://graph.facebook.com/debug_token"
                    params = {
                        "input_token": token,
                        "access_token": f"{app_id}|{app_secret}",
                    }
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(debug_url, params=params)
                        data = (resp.json() or {}).get("data") or {}
                    is_valid = bool(data.get("is_valid"))
                    scopes = data.get("scopes") or []
                    normalized_scopes = {
                        str(scope.get("scope") if isinstance(scope, dict) else scope).strip()
                        for scope in scopes
                        if scope
                    }
                    required = {"whatsapp_business_management", "whatsapp_business_messaging"}
                    missing_scopes = [] if "*" in normalized_scopes else sorted(required - normalized_scopes)
                    if not is_valid:
                        integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                        cred.last_health_status = "invalid"
                        cred.last_health_error_code = "token_invalid"
                        await AuditLogService(db).write(
                            action="whatsapp.credential.health",
                            resource_type="oauth_credential",
                            status="failed",
                            business_id=cred.business_id,
                            actor_type="system",
                            resource_id=str(cred.id),
                            details={"reason": "token_invalid"},
                        )
                        await OnboardingEventLedgerService(db).append(
                            business_id=cred.business_id,
                            operation_id=f"credential_health_{cred.id}",
                            event_type="credential_invalid",
                            event_status="failed",
                            graph_error_code="token_invalid",
                            error_message="debug_token invalid",
                        )
                    elif missing_scopes:
                        integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                        cred.last_health_status = "scope_missing"
                        cred.last_health_error_code = "required_scope_missing"
                        await AuditLogService(db).write(
                            action="whatsapp.credential.health",
                            resource_type="oauth_credential",
                            status="failed",
                            business_id=cred.business_id,
                            actor_type="system",
                            resource_id=str(cred.id),
                            details={"reason": "required_scope_missing", "missing_scopes": missing_scopes},
                        )
                        await OnboardingEventLedgerService(db).append(
                            business_id=cred.business_id,
                            operation_id=f"credential_health_{cred.id}",
                            event_type="credential_scope_missing",
                            event_status="failed",
                            graph_error_code="required_scope_missing",
                            graph_response_json={"missing_scopes": missing_scopes},
                            error_message="required scopes missing",
                        )
                    else:
                        if integration.status in {"reconnect_required", "provisioning"}:
                            # Keep provisioning flow intact; only auto-heal reconnect_required.
                            if integration.status == "reconnect_required":
                                integration.status = transition_whatsapp_integration_status(integration.status, "connected")
                        cred.last_health_status = "healthy"
                        cred.last_health_error_code = None
                        await OnboardingEventLedgerService(db).append(
                            business_id=cred.business_id,
                            operation_id=f"credential_health_{cred.id}",
                            event_type="credential_health_ok",
                            event_status="success",
                        )
                    cred.last_health_check_at = now
                except Exception as exc:
                    integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                    cred.last_health_check_at = now
                    cred.last_health_status = "error"
                    cred.last_health_error_code = "health_check_failed"
                    await AuditLogService(db).write(
                        action="whatsapp.credential.health",
                        resource_type="oauth_credential",
                        status="failed",
                        business_id=cred.business_id,
                        actor_type="system",
                        resource_id=str(cred.id),
                        details={"reason": "health_check_failed", "error": str(exc)},
                    )
                    await OnboardingEventLedgerService(db).append(
                        business_id=cred.business_id,
                        operation_id=f"credential_health_{cred.id}",
                        event_type="credential_health_check_failed",
                        event_status="failed",
                        graph_error_code="health_check_failed",
                        error_message=str(exc),
                    )
            await db.commit()

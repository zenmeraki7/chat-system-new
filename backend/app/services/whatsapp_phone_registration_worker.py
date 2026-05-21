from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.business_domains import (
    OAuthCredential,
    EmbeddedSignupSession,
    OnboardingOperation,
    OutboxEvent,
    MessageOutbox,
    PhoneRegistrationAttempt,
    WhatsAppIntegration,
    WhatsAppPhoneNumber,
)
from app.services.audit_log_service import AuditLogService
from app.services.whatsapp_phone_readiness import whatsapp_phone_readiness_policy
from app.services.token_crypto_service import token_crypto_service
from app.services.whatsapp_service import whatsapp_service
from app.services.whatsapp_onboarding_state_machine import transition_onboarding_state
from app.services.whatsapp_integration_state_machine import transition_whatsapp_integration_status
from app.services.onboarding_event_ledger_service import OnboardingEventLedgerService

logger = logging.getLogger(__name__)


class WhatsAppPhoneRegistrationWorker:
    def __init__(self, *, poll_interval_seconds: float = 2.0, max_attempts: int = 8) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.max_attempts = max_attempts
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
                processed_any = await self._process_one()
                if not processed_any:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("whatsapp_phone_registration_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "whatsapp.phone.register",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= now,
                    OutboxEvent.deleted_at.is_(None),
                )
                .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            event = row.scalar_one_or_none()
            if event is None:
                return False

            event.attempts = int(event.attempts or 0) + 1
            payload = event.payload_json or {}
            business_id_raw = str(payload.get("business_id") or "")
            phone_number_id = str(payload.get("phone_number_id") or "")
            operation_id = str(payload.get("onboarding_operation_id") or "")
            if not business_id_raw or not phone_number_id:
                event.status = "failed"
                event.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            try:
                business_id = UUID(business_id_raw)
            except ValueError:
                event.status = "failed"
                event.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            try:
                cred_row = await db.execute(
                    select(OAuthCredential)
                    .where(
                        OAuthCredential.business_id == business_id,
                        OAuthCredential.provider == "whatsapp",
                        OAuthCredential.environment == "live",
                        OAuthCredential.revoked_at.is_(None),
                    )
                    .order_by(OAuthCredential.created_at.desc())
                    .limit(1)
                )
                credential = cred_row.scalars().first()
                if credential is None:
                    raise ValueError("Missing active whatsapp credential")
                token = token_crypto_service.decrypt(credential.access_token_ciphertext)

                register_resp = await whatsapp_service.register_phone_number(phone_number_id=phone_number_id, token=token)
                profile = await whatsapp_service.get_phone_number_operational_profile(phone_number_id=phone_number_id, token=token)
                payload["last_profile"] = profile
                readiness = whatsapp_phone_readiness_policy.evaluate(profile)
                ready = readiness.ready
                db.add(
                    PhoneRegistrationAttempt(
                        business_id=business_id,
                        phone_number_id=phone_number_id,
                        waba_id=str(payload.get("waba_id") or "") or None,
                        onboarding_operation_id=operation_id or None,
                        outbox_event_id=event.id,
                        attempt_number=int(event.attempts),
                        result_status="success" if ready else "pending",
                        http_status_code=200,
                        response_payload_json={"register": register_resp, "profile": profile, "readiness": readiness.reason},
                        error_payload_json=None,
                    )
                )

                phone_row = await db.execute(
                    select(WhatsAppPhoneNumber)
                    .where(
                        WhatsAppPhoneNumber.business_id == business_id,
                        WhatsAppPhoneNumber.phone_number_id == phone_number_id,
                        WhatsAppPhoneNumber.environment == "live",
                        WhatsAppPhoneNumber.disconnected_at.is_(None),
                        WhatsAppPhoneNumber.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                phone = phone_row.scalar_one_or_none()
                if phone is not None:
                    phone.display_phone_number = profile.get("display_phone_number")
                    phone.verified_name = profile.get("verified_name")
                    phone.quality_rating = profile.get("quality_rating")
                    phone.messaging_limit_tier = profile.get("messaging_limit_tier")
                    phone.verification_status = profile.get("code_verification_status")
                    phone.last_health_check_at = datetime.now(timezone.utc)
                    phone.last_health_status = "healthy" if ready else "pending"
                    phone.last_health_error_code = None if ready else readiness.reason
                    if ready:
                        phone.status = "active"
                        phone.sending_status = "enabled"

                if operation_id:
                    await self._update_onboarding_progress(
                        db=db,
                        business_id=business_id,
                        operation_id=operation_id,
                        ready=ready,
                        failure_reason=None,
                        onboarding_session_id=str(payload.get("onboarding_session_id") or ""),
                    )

                if ready:
                    integ_row = await db.execute(
                        select(WhatsAppIntegration)
                        .where(WhatsAppIntegration.business_id == business_id)
                        .with_for_update()
                    )
                    integration = integ_row.scalar_one_or_none()
                    if integration is not None:
                        # Keep provisioning until operational probe and webhook evidence are verified.
                        if integration.status == "reconnect_required":
                            integration.status = transition_whatsapp_integration_status(integration.status, "provisioning")
                    event.status = "processed"
                    event.processed_at = datetime.now(timezone.utc)
                    await AuditLogService(db).write(
                        action="whatsapp.phone.register",
                        resource_type="whatsapp_phone_number",
                        status="success",
                        business_id=business_id,
                        actor_type="system",
                        resource_id=phone_number_id,
                        details={"register_response": register_resp, "profile": profile, "readiness": readiness.reason},
                    )
                    await OnboardingEventLedgerService(db).append(
                        business_id=business_id,
                        operation_id=operation_id or None,
                        event_type="phone_registration_verified",
                        event_status="success",
                        waba_id=str(payload.get("waba_id") or "") or None,
                        phone_number_id=phone_number_id,
                        graph_api_endpoint=f"/{phone_number_id}/register",
                        graph_response_json={"register": register_resp, "profile": profile},
                    )
                    probe_recipient = str(settings.WHATSAPP_ONBOARDING_PROBE_RECIPIENT_E164 or "").strip()
                    if probe_recipient:
                        existing_probe = (
                            await db.execute(
                                select(MessageOutbox.id)
                                .where(
                                    MessageOutbox.business_id == business_id,
                                    MessageOutbox.source_type == "onboarding_probe",
                                    MessageOutbox.status.in_(["pending", "sending", "sent"]),
                                    MessageOutbox.deleted_at.is_(None),
                                )
                                .order_by(MessageOutbox.created_at.desc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if existing_probe is None:
                            probe_text = str(settings.WHATSAPP_ONBOARDING_PROBE_TEXT or "").strip() or "Operational probe"
                            probe_key = f"onboarding_probe:{business_id}:{phone_number_id}:{int(datetime.now(timezone.utc).timestamp())}"
                            db.add(
                                MessageOutbox(
                                    business_id=business_id,
                                    phone_number_id=phone_number_id,
                                    to_phone_e164=probe_recipient,
                                    message_type="text",
                                    payload_json={"text": probe_text},
                                    source_type="onboarding_probe",
                                    priority=5,
                                    scheduled_at=datetime.now(timezone.utc),
                                    idempotency_key=probe_key,
                                    status="pending",
                                )
                            )
                            await OnboardingEventLedgerService(db).append(
                                business_id=business_id,
                                operation_id=operation_id or None,
                                event_type="onboarding_operational_probe_enqueued",
                                event_status="success",
                                waba_id=str(payload.get("waba_id") or "") or None,
                                phone_number_id=phone_number_id,
                                graph_response_json={"recipient": probe_recipient},
                            )
                else:
                    logger.info(
                        "whatsapp_phone_registration_pending business_id=%s phone_number_id=%s readiness=%s profile=%s",
                        str(business_id),
                        phone_number_id,
                        readiness.reason,
                        profile,
                    )
                    if event.attempts >= self.max_attempts:
                        event.status = "failed"
                        event.processed_at = datetime.now(timezone.utc)
                        integ_row = await db.execute(
                            select(WhatsAppIntegration)
                            .where(WhatsAppIntegration.business_id == business_id)
                            .with_for_update()
                        )
                        integration = integ_row.scalar_one_or_none()
                        if integration is not None:
                            integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                        if operation_id:
                            await self._update_onboarding_progress(
                                db=db,
                                business_id=business_id,
                                operation_id=operation_id,
                                ready=False,
                                failure_reason="registration_pending_timeout",
                                onboarding_session_id=str(payload.get("onboarding_session_id") or ""),
                            )
                        await OnboardingEventLedgerService(db).append(
                            business_id=business_id,
                            operation_id=operation_id or None,
                            event_type="phone_registration_failed_timeout",
                            event_status="failed",
                            waba_id=str(payload.get("waba_id") or "") or None,
                            phone_number_id=phone_number_id,
                            graph_api_endpoint=f"/{phone_number_id}/register",
                            error_message="registration_pending_timeout",
                            graph_response_json={"profile": profile, "readiness": readiness.reason},
                        )
                    else:
                        event.status = "pending"
                        event.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(300, 15 * int(event.attempts)))
                await db.commit()
                return True
            except Exception as exc:
                http_status_code = None
                provider_error_code = None
                provider_error_subcode = None
                error_payload_json: dict | None = None
                if isinstance(exc, httpx.HTTPStatusError):
                    http_status_code = exc.response.status_code
                    try:
                        err_json = exc.response.json()
                    except Exception:
                        err_json = {"raw_body": exc.response.text}
                    error_payload_json = err_json if isinstance(err_json, dict) else {"payload": err_json}
                    provider_error = (error_payload_json or {}).get("error") if isinstance(error_payload_json, dict) else None
                    if isinstance(provider_error, dict):
                        if provider_error.get("code") is not None:
                            provider_error_code = str(provider_error.get("code"))
                        if provider_error.get("error_subcode") is not None:
                            provider_error_subcode = str(provider_error.get("error_subcode"))
                else:
                    error_payload_json = {"error": str(exc)}
                db.add(
                    PhoneRegistrationAttempt(
                        business_id=business_id,
                        phone_number_id=phone_number_id,
                        waba_id=str(payload.get("waba_id") or "") or None,
                        onboarding_operation_id=operation_id or None,
                        outbox_event_id=event.id,
                        attempt_number=int(event.attempts),
                        result_status="failed" if int(event.attempts) >= self.max_attempts else "retrying",
                        http_status_code=http_status_code,
                        provider_error_code=provider_error_code,
                        provider_error_subcode=provider_error_subcode,
                        response_payload_json=None,
                        error_payload_json=error_payload_json,
                    )
                )
                if event.attempts >= self.max_attempts:
                    event.status = "failed"
                    event.processed_at = datetime.now(timezone.utc)
                    integ_row = await db.execute(
                        select(WhatsAppIntegration)
                        .where(WhatsAppIntegration.business_id == business_id)
                        .with_for_update()
                    )
                    integration = integ_row.scalar_one_or_none()
                    if integration is not None:
                        integration.status = transition_whatsapp_integration_status(integration.status, "reconnect_required")
                    if operation_id:
                        await self._update_onboarding_progress(
                            db=db,
                            business_id=business_id,
                            operation_id=operation_id,
                            ready=False,
                            failure_reason=str(exc),
                            onboarding_session_id=str(payload.get("onboarding_session_id") or ""),
                        )
                else:
                    event.status = "pending"
                    event.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** int(event.attempts)))
                await AuditLogService(db).write(
                    action="whatsapp.phone.register",
                    resource_type="whatsapp_phone_number",
                    status="failed",
                    business_id=business_id,
                    actor_type="system",
                    resource_id=phone_number_id,
                    details={"error": str(exc), "attempt": int(event.attempts), "profile": payload.get("last_profile")},
                )
                await OnboardingEventLedgerService(db).append(
                    business_id=business_id,
                    operation_id=operation_id or None,
                    event_type="phone_registration_attempt_failed",
                    event_status="failed",
                    waba_id=str(payload.get("waba_id") or "") or None,
                    phone_number_id=phone_number_id,
                    graph_api_endpoint=f"/{phone_number_id}/register",
                    graph_error_code=provider_error_code,
                    graph_error_subcode=provider_error_subcode,
                    error_message=str(exc),
                    graph_response_json=error_payload_json if isinstance(error_payload_json, dict) else None,
                )
                await db.commit()
                return True

    async def _update_onboarding_progress(
        self,
        *,
        db,
        business_id: UUID,
        operation_id: str,
        ready: bool,
        failure_reason: str | None,
        onboarding_session_id: str,
    ) -> None:
        if not operation_id:
            raise ValueError("Missing onboarding operation id for registration progress update")
        op_res = await db.execute(
            select(OnboardingOperation)
            .where(
                OnboardingOperation.business_id == business_id,
                OnboardingOperation.operation_id == operation_id,
            )
            .with_for_update()
            .limit(1)
        )
        op = op_res.scalar_one_or_none()
        if op is None:
            raise ValueError("Onboarding operation not found for registration progress update")
        if ready:
            result = transition_onboarding_state(op.current_step, "phone_registration_verified")
            op.current_step = result.current_step
            op.status = result.status
            op.compensating_action_required = result.compensating_action_required
        else:
            if failure_reason:
                result = transition_onboarding_state(op.current_step, "phone_registration_failed")
                op.current_step = result.current_step
                op.status = result.status
                op.compensating_action_required = result.compensating_action_required
            else:
                result = transition_onboarding_state(op.current_step, "phone_registration_pending")
                op.current_step = result.current_step
                op.status = result.status
                op.compensating_action_required = result.compensating_action_required
        if onboarding_session_id:
            try:
                session_id = UUID(onboarding_session_id)
            except ValueError:
                session_id = None
            if session_id is not None:
                sess_row = await db.execute(
                    select(EmbeddedSignupSession)
                    .where(
                        EmbeddedSignupSession.id == session_id,
                        EmbeddedSignupSession.business_id == business_id,
                    )
                    .with_for_update()
                    .limit(1)
                )
                signup_session = sess_row.scalar_one_or_none()
                if signup_session is not None:
                    if ready:
                        signup_session.status = "completed"
                        signup_session.completed_at = datetime.now(timezone.utc)
                    elif failure_reason:
                        signup_session.status = "failed"
                        signup_session.failed_at = datetime.now(timezone.utc)
                        signup_session.failure_reason = "phone_registration_failed"
                    else:
                        signup_session.status = "pending"

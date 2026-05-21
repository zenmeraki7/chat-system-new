from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.status_enums import BusinessOnboardingStatus
from app.models.business import Business
from app.models.business_domains import (
    MessageOutbox,
    MessageStatusEvent,
    OAuthCredential,
    WebhookSubscription,
    WhatsAppIntegration,
    WhatsAppPhoneNumber,
)
from app.services.audit_log_service import AuditLogService
from app.services.onboarding_event_ledger_service import OnboardingEventLedgerService
from app.services.whatsapp_integration_state_machine import transition_whatsapp_integration_status
from app.services.whatsapp_phone_readiness import whatsapp_phone_readiness_policy


@dataclass
class OnboardingHealthProjection:
    credential_health: str
    subscription_health: str
    phone_readiness: str
    webhook_heartbeat: str
    probe_send: str
    unified_state: str
    reason: str


class WhatsAppOnboardingHealthProjector:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditLogService(db)
        self.ledger = OnboardingEventLedgerService(db)

    async def project_and_apply(self, *, business_id: UUID, actor_user_id: UUID | None = None, trigger: str = "worker") -> OnboardingHealthProjection:
        now = datetime.now(timezone.utc)
        integration = (
            await self.db.execute(
                select(WhatsAppIntegration).where(WhatsAppIntegration.business_id == business_id).limit(1)
            )
        ).scalar_one_or_none()
        credential = (
            await self.db.execute(
                select(OAuthCredential)
                .where(
                    OAuthCredential.business_id == business_id,
                    OAuthCredential.provider == "whatsapp",
                    OAuthCredential.environment == "live",
                    OAuthCredential.revoked_at.is_(None),
                    OAuthCredential.deleted_at.is_(None),
                )
                .order_by(OAuthCredential.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        webhook = (
            await self.db.execute(
                select(WebhookSubscription)
                .where(
                    WebhookSubscription.business_id == business_id,
                    WebhookSubscription.provider == "whatsapp",
                    WebhookSubscription.deleted_at.is_(None),
                )
                .order_by(WebhookSubscription.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        phone = (
            await self.db.execute(
                select(WhatsAppPhoneNumber)
                .where(
                    WhatsAppPhoneNumber.business_id == business_id,
                    WhatsAppPhoneNumber.disconnected_at.is_(None),
                    WhatsAppPhoneNumber.deleted_at.is_(None),
                )
                .order_by(WhatsAppPhoneNumber.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        business = await self.db.get(Business, business_id)

        credential_health = "missing"
        if credential is not None:
            h = str(credential.last_health_status or "").strip().lower()
            if h in {"healthy"}:
                credential_health = "healthy"
            elif h in {"expired", "invalid", "scope_missing", "error"}:
                credential_health = "unhealthy"
            else:
                credential_health = "unknown"

        subscription_health = "missing"
        if webhook is not None:
            h = str(webhook.last_health_status or "").strip().lower()
            status = str(webhook.status or "").strip().lower()
            fields = {str(x).strip().lower() for x in (webhook.subscribed_fields or []) if str(x).strip()}
            if status == "active" and h == "healthy" and "messages" in fields:
                subscription_health = "healthy"
            elif status in {"degraded", "inactive"} or h in {"error", "degraded"}:
                subscription_health = "unhealthy"
            else:
                subscription_health = "unknown"

        phone_readiness = "missing"
        if phone is not None:
            readiness = whatsapp_phone_readiness_policy.evaluate(
                {
                    "code_verification_status": phone.verification_status,
                    "status": phone.status,
                    "platform_type": None,
                }
            )
            phone_readiness = "ready" if readiness.ready else "not_ready"

        webhook_heartbeat = "missing"
        if webhook is not None:
            ts = webhook.last_webhook_received_at
            if ts is None:
                webhook_heartbeat = "awaiting_first_event"
            elif ts >= (now - timedelta(hours=24)):
                webhook_heartbeat = "healthy"
            elif ts >= (now - timedelta(days=3)):
                webhook_heartbeat = "stale"
            else:
                webhook_heartbeat = "dead"

        probe_send = await self._probe_state(business_id=business_id)

        unified_state = "provisioning"
        reason = "awaiting_requirements"
        all_green = (
            credential_health == "healthy"
            and subscription_health == "healthy"
            and phone_readiness == "ready"
            and webhook_heartbeat in {"healthy", "stale"}
            and probe_send == "webhook_observed"
        )
        hard_fail = (
            credential_health == "unhealthy"
            or subscription_health == "unhealthy"
            or webhook_heartbeat == "dead"
            or probe_send == "failed"
        )
        if all_green:
            unified_state = "connected"
            reason = "operational_probe_verified"
        elif hard_fail:
            unified_state = "reconnect_required"
            reason = "critical_signal_failed"

        if integration is not None:
            if unified_state != integration.status:
                try:
                    integration.status = transition_whatsapp_integration_status(integration.status, unified_state)
                except ValueError:
                    # Keep state machine strict; do not force invalid edge from disconnected flows.
                    pass
        if business is not None:
            previous = str(business.onboarding_status or "").strip().lower()
            if unified_state == "connected":
                business.onboarding_status = BusinessOnboardingStatus.COMPLETED.value
            elif unified_state == "reconnect_required":
                business.onboarding_status = BusinessOnboardingStatus.FAILED.value
            else:
                business.onboarding_status = BusinessOnboardingStatus.IN_PROGRESS.value
            if previous != business.onboarding_status:
                await self.audit.write(
                    action="whatsapp.onboarding.state_projection",
                    resource_type="whatsapp_integration",
                    status="success",
                    business_id=business_id,
                    user_id=actor_user_id,
                    actor_type="system" if actor_user_id is None else "user",
                    actor_id=(str(actor_user_id) if actor_user_id else None),
                    resource_id=str(business_id),
                    details={
                        "trigger": trigger,
                        "previous_onboarding_status": previous,
                        "new_onboarding_status": business.onboarding_status,
                        "unified_state": unified_state,
                        "reason": reason,
                    },
                )
        await self.ledger.append(
            business_id=business_id,
            operation_id=f"onboarding_projection_{business_id}",
            event_type="onboarding_operational_projection",
            event_status="success",
            merchant_user_id=actor_user_id,
            graph_response_json={
                "trigger": trigger,
                "credential_health": credential_health,
                "subscription_health": subscription_health,
                "phone_readiness": phone_readiness,
                "webhook_heartbeat": webhook_heartbeat,
                "probe_send": probe_send,
                "unified_state": unified_state,
                "reason": reason,
            },
        )
        return OnboardingHealthProjection(
            credential_health=credential_health,
            subscription_health=subscription_health,
            phone_readiness=phone_readiness,
            webhook_heartbeat=webhook_heartbeat,
            probe_send=probe_send,
            unified_state=unified_state,
            reason=reason,
        )

    async def _probe_state(self, *, business_id: UUID) -> str:
        outbox = (
            await self.db.execute(
                select(MessageOutbox)
                .where(
                    MessageOutbox.business_id == business_id,
                    MessageOutbox.source_type == "onboarding_probe",
                    MessageOutbox.deleted_at.is_(None),
                )
                .order_by(MessageOutbox.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if outbox is None:
            return "not_attempted"
        if str(outbox.status or "").lower() in {"failed", "cancelled"}:
            return "failed"
        provider_message_id = str(outbox.provider_message_id or "").strip()
        if not provider_message_id:
            return "send_accepted_waiting_provider_id"
        status_evt = (
            await self.db.execute(
                select(MessageStatusEvent)
                .where(
                    MessageStatusEvent.business_id == business_id,
                    MessageStatusEvent.provider_message_id == provider_message_id,
                    MessageStatusEvent.deleted_at.is_(None),
                )
                .order_by(MessageStatusEvent.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if status_evt is None:
            return "provider_sent_waiting_webhook"
        st = str(status_evt.status or status_evt.provider_status or "").strip().lower()
        if st in {"accepted", "sent", "delivered", "read"}:
            return "webhook_observed"
        if st == "failed":
            return "failed"
        return "provider_sent_waiting_webhook"

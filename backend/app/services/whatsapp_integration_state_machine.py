from __future__ import annotations

from app.domain.status_enums import WhatsAppIntegrationStatus


_ALLOWED_INTEGRATION_TRANSITIONS: dict[str, set[str]] = {
    WhatsAppIntegrationStatus.DISCONNECTED.value: {
        WhatsAppIntegrationStatus.PROVISIONING.value,
    },
    WhatsAppIntegrationStatus.PROVISIONING.value: {
        WhatsAppIntegrationStatus.CONNECTED.value,
        WhatsAppIntegrationStatus.RECONNECT_REQUIRED.value,
        WhatsAppIntegrationStatus.DISCONNECTED.value,
    },
    WhatsAppIntegrationStatus.CONNECTED.value: {
        WhatsAppIntegrationStatus.PROVISIONING.value,
        WhatsAppIntegrationStatus.RECONNECT_REQUIRED.value,
        WhatsAppIntegrationStatus.DISCONNECTING.value,
    },
    WhatsAppIntegrationStatus.RECONNECT_REQUIRED.value: {
        WhatsAppIntegrationStatus.PROVISIONING.value,
        WhatsAppIntegrationStatus.CONNECTED.value,
        WhatsAppIntegrationStatus.DISCONNECTING.value,
        WhatsAppIntegrationStatus.DISCONNECTED.value,
    },
    WhatsAppIntegrationStatus.DISCONNECTING.value: {
        WhatsAppIntegrationStatus.DISCONNECTED.value,
    },
}


def transition_whatsapp_integration_status(current_status: str | None, next_status: str) -> str:
    source = str(current_status or WhatsAppIntegrationStatus.DISCONNECTED.value).strip().lower()
    target = str(next_status or "").strip().lower()
    if not target:
        raise ValueError("next integration status must be provided")
    if source == target:
        return source
    allowed = _ALLOWED_INTEGRATION_TRANSITIONS.get(source)
    if not allowed:
        raise ValueError(f"unknown integration status: {source}")
    if target not in allowed:
        raise ValueError(f"invalid integration transition: {source} -> {target}")
    return target


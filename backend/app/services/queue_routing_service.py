from __future__ import annotations

from app.config import settings


def classify_outbox_event(event_type: str) -> tuple[str, str]:
    normalized = str(event_type or "").strip().lower()
    if normalized.startswith("webhook."):
        return "webhooks", "hot"
    if normalized in {"whatsapp.send.outbound", "campaign_dispatch_job", "campaign_batch_dispatch_job"}:
        return "send", "hot"
    if normalized.startswith("conversation."):
        return "inbox", "hot"
    if normalized.startswith("campaign.") or normalized.startswith("bulk_job."):
        return "campaign", "cold"
    if normalized.startswith("contact_export."):
        return "exports", "cold"
    return "generic", "cold"


def worker_region_normalized() -> str:
    return str(settings.WORKER_REGION or "global").strip().lower() or "global"


def can_process_region(queue_region: str | None) -> bool:
    configured = worker_region_normalized()
    if configured == "global":
        return True
    event_region = str(queue_region or "global").strip().lower()
    return event_region in {"global", configured}


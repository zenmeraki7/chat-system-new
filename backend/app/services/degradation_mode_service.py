from __future__ import annotations

from app.config import settings


_COLD_DOMAINS = {"analytics", "exports", "bulk", "campaign_cold"}


def is_degradation_active() -> bool:
    mode = str(settings.DEGRADATION_MODE or "normal").strip().lower()
    return mode in {"degraded", "hot_path_only"}


def should_defer_domain(domain: str) -> bool:
    if not is_degradation_active():
        return False
    return str(domain or "").strip().lower() in _COLD_DOMAINS


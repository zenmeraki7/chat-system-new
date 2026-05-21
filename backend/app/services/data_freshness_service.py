from __future__ import annotations

from datetime import datetime, timezone


def freshness_live_db(*, generated_at: datetime | None = None) -> dict:
    ts = generated_at or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return {
        "source": "live_db",
        "generatedAt": ts.isoformat(),
        "maxLagSeconds": 0,
        "stale": False,
    }


def freshness_snapshot(*, generated_at: datetime | None, max_lag_seconds: int) -> dict:
    now = datetime.now(timezone.utc)
    ts = generated_at or now
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    lag = max(0, int((now - ts).total_seconds()))
    return {
        "source": "snapshot",
        "generatedAt": ts.isoformat(),
        "maxLagSeconds": max_lag_seconds,
        "stale": lag > max_lag_seconds,
    }


from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Any


class InMemoryMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Counter[str] = Counter()

    def increment(self, name: str, *, tags: dict[str, Any] | None = None, value: int = 1) -> None:
        tags = tags or {}
        normalized = ",".join(f"{k}={tags[k]}" for k in sorted(tags.keys()))
        key = f"{name}|{normalized}" if normalized else name
        with self._lock:
            self._counters[key] += int(value)

    def get(self, name: str, *, tags: dict[str, Any] | None = None) -> int:
        tags = tags or {}
        normalized = ",".join(f"{k}={tags[k]}" for k in sorted(tags.keys()))
        key = f"{name}|{normalized}" if normalized else name
        with self._lock:
            return int(self._counters.get(key, 0))


metrics = InMemoryMetrics()


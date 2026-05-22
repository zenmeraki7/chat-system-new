from __future__ import annotations


def normalize_search(search: str | None) -> str | None:
    if not search:
        return None
    normalized = " ".join(str(search).strip().lower().split())
    if not normalized:
        return None
    if len(normalized) < 2:
        return None
    if len(normalized) > 100:
        raise ValueError("SEARCH_TOO_LONG")
    return normalized


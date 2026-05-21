from __future__ import annotations

from dataclasses import dataclass
from fastapi import HTTPException


@dataclass(frozen=True)
class TableConfig:
    allowed_sorts: tuple[str, ...]
    allowed_filters: tuple[str, ...]
    default_sort: str
    default_limit: int
    max_limit: int
    exportable_columns: tuple[str, ...] = ()
    sensitive_columns: tuple[str, ...] = ()


TABLE_REGISTRY: dict[str, TableConfig] = {
    "contacts": TableConfig(
        allowed_sorts=("updated_at", "name", "phone_e164", "last_message_at"),
        allowed_filters=("tag", "opt_in_status", "suppressed", "segment_id"),
        default_sort="updated_at",
        default_limit=100,
        max_limit=250,
        exportable_columns=("name", "phone_e164", "tags", "opt_in_status", "email", "updated_at"),
        sensitive_columns=("phone_e164", "email", "custom_attributes"),
    ),
    "campaign_recipients": TableConfig(
        allowed_sorts=("updated_at", "sent_at", "status"),
        allowed_filters=("status", "last_error_code", "search"),
        default_sort="updated_at",
        default_limit=100,
        max_limit=250,
        exportable_columns=("name", "phone_e164", "status", "last_error_code", "sent_at"),
        sensitive_columns=("phone_e164", "last_error_code", "last_error_message"),
    ),
}


def get_table_config(table: str) -> TableConfig:
    cfg = TABLE_REGISTRY.get(str(table or "").strip())
    if cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown table: {table}")
    return cfg


def validate_table_query(*, table: str, sort_by: str, sort_dir: str, limit: int, filters: dict) -> tuple[str, str, int]:
    cfg = get_table_config(table)
    resolved_sort = sort_by if sort_by in cfg.allowed_sorts else cfg.default_sort
    resolved_dir = "asc" if str(sort_dir).lower() == "asc" else "desc"
    resolved_limit = max(1, min(int(limit or cfg.default_limit), cfg.max_limit))
    for k, v in (filters or {}).items():
        if v is None or v == "":
            continue
        if k not in cfg.allowed_filters:
            raise HTTPException(status_code=400, detail=f"Unsupported filter for {table}: {k}")
    # Simple query performance budget guard.
    if isinstance(filters.get("search"), str) and len(filters.get("search").strip()) > 0 and len(filters.get("search").strip()) < 2:
        raise HTTPException(status_code=400, detail="Search query too short for indexed lookup")
    return resolved_sort, resolved_dir, resolved_limit


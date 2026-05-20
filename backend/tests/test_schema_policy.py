from __future__ import annotations

from sqlalchemy.sql.schema import Table

from app.database import Base
import app.models.registry  # noqa: F401
from app.schema_policy.registry import (
    classify_table,
    GLOBAL_TABLES,
    requires_business_id,
    is_immutable_event,
    is_public_api_entity,
)


# Transitional exceptions for known legacy drift that must be burned down over time.
LEGACY_BUSINESS_ID_NULLABLE_ALLOWLIST = {
    "webhook_events",
    "provider_webhook_events",
    "provider_request_logs",
    "outbox_events",
    "pricing_catalogs",
    "provider_integrations",
    "identity_providers",
    "seats",
}

LEGACY_IMMUTABLE_HAS_UPDATED_AT_ALLOWLIST = {
    "usage_ledger",
    "billing_ledger",
    "message_status_events",
    "webhook_events",
    "provider_webhook_events",
    "campaign_approval_snapshots",
}


def _tables() -> dict[str, Table]:
    return Base.metadata.tables


def test_every_table_has_primary_key() -> None:
    for table_name, table in _tables().items():
        assert table.primary_key is not None and len(table.primary_key.columns) > 0, table_name


def test_mutable_tables_have_timestamps() -> None:
    for table_name, table in _tables().items():
        classification = classify_table(table_name)
        if classification in {"tenant_mutable_entity", "global_entity", "tenant_secret_container"}:
            assert "created_at" in table.c, f"{table_name} missing created_at"
            assert "updated_at" in table.c, f"{table_name} missing updated_at"


def test_tenant_tables_have_business_id() -> None:
    for table_name, table in _tables().items():
        if not requires_business_id(table_name):
            continue
        assert "business_id" in table.c, f"{table_name} missing business_id"
        if table_name in LEGACY_BUSINESS_ID_NULLABLE_ALLOWLIST:
            continue
        assert table.c["business_id"].nullable is False, f"{table_name}.business_id must be NOT NULL"


def test_tables_without_business_id_are_global_or_explicit_exception() -> None:
    allowed_no_business_id = GLOBAL_TABLES | LEGACY_BUSINESS_ID_NULLABLE_ALLOWLIST
    for table_name, table in _tables().items():
        if "business_id" in table.c:
            continue
        classification = classify_table(table_name)
        assert (
            table_name in allowed_no_business_id or classification == "global_entity"
        ), f"{table_name} lacks business_id but is not in GLOBAL_TABLES/exception allowlist"


def test_event_tables_are_append_only_shape() -> None:
    for table_name, table in _tables().items():
        if not is_immutable_event(table_name):
            continue
        assert "created_at" in table.c, f"{table_name} missing created_at"
        if table_name in LEGACY_IMMUTABLE_HAS_UPDATED_AT_ALLOWLIST:
            continue
        assert "updated_at" not in table.c, f"{table_name} should not have updated_at"


def test_public_api_entities_have_public_id() -> None:
    for table_name, table in _tables().items():
        if is_public_api_entity(table_name):
            assert "public_id" in table.c, f"{table_name} missing public_id"

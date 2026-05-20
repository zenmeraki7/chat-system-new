from __future__ import annotations

import app.models.registry  # noqa: F401
from app.database import Base


# Business-critical tables that must never be hard-cascade deleted when parent business is deleted.
RESTRICT_ON_BUSINESS_DELETE = {
    "messages",
    "audit_logs",
    "campaigns",
    "usage_ledger",
    "compliance_evidence",
    "provider_webhook_events",
    "provider_request_logs",
    "business_events",
    "billing_usage_daily",
    "message_metrics_daily",
}

# Allowed hard cascades for ephemeral/setup tables.
CASCADE_ALLOWED_ON_BUSINESS_DELETE = {
    "business_widget_settings",
    "embedded_signup_sessions",
}

# Transitional exceptions where current schema still uses CASCADE and needs migration burn-down.
TRANSITIONAL_CASCADE_EXCEPTIONS = {
    "audit_logs.business_id",
    "messages.business_id",
    "campaigns.business_id",
    "usage_ledger.business_id",
    "provider_webhook_events.business_id",
    "provider_request_logs.business_id",
    "business_events.business_id",
    "billing_usage_daily.business_id",
    "message_metrics_daily.business_id",
}


def test_business_fk_delete_policy_standard() -> None:
    violations: list[str] = []
    for table in Base.metadata.tables.values():
        if "business_id" not in table.columns:
            continue
        col = table.columns["business_id"]
        if not col.foreign_keys:
            continue
        for fk in col.foreign_keys:
            target = fk.column.table.name
            if target != "businesses":
                continue
            ondelete = (fk.ondelete or "").upper()
            fq = f"{table.name}.business_id"

            if table.name in CASCADE_ALLOWED_ON_BUSINESS_DELETE:
                if ondelete != "CASCADE":
                    violations.append(f"{fq} expected CASCADE")
                continue

            if table.name in RESTRICT_ON_BUSINESS_DELETE:
                if ondelete == "CASCADE" and fq not in TRANSITIONAL_CASCADE_EXCEPTIONS:
                    violations.append(f"{fq} must not CASCADE")

    assert not violations, " ; ".join(violations)


def test_orm_delete_orphan_aligned_with_db_cascade() -> None:
    violations: list[str] = []
    for mapper in Base.registry.mappers:
        parent = mapper.class_
        parent_table = mapper.local_table.name
        for rel in mapper.relationships:
            if "delete-orphan" not in rel.cascade:
                continue
            child_table = rel.mapper.local_table.name
            # Find child->parent fk(s)
            fks = [
                fk for fk in rel.mapper.local_table.foreign_keys if fk.column.table.name == parent_table
            ]
            if not fks:
                continue
            if not any((fk.ondelete or "").upper() == "CASCADE" for fk in fks):
                violations.append(f"{parent.__name__}.{rel.key} delete-orphan without DB CASCADE")

    assert not violations, " ; ".join(violations)

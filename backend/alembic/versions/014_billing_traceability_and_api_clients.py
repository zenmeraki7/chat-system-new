"""Billing traceability, residency, status history, legal hold, impersonation, API clients, and customer webhooks

Revision ID: 014_billing_traceability_and_api_clients
Revises: 013_org_workspace_agent_and_knowledge_pricing
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "014_billing_traceability_and_api_clients"
down_revision = "013_org_workspace_agent_and_knowledge_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("data_region", sa.String(length=10), nullable=True))
    op.execute("UPDATE businesses SET data_region = 'US' WHERE data_region IS NULL")
    op.alter_column("businesses", "data_region", nullable=False)

    op.add_column("workspaces", sa.Column("data_region", sa.String(length=10), nullable=True))
    op.execute("UPDATE workspaces SET data_region = 'US' WHERE data_region IS NULL")
    op.alter_column("workspaces", "data_region", nullable=False)

    op.add_column("campaigns", sa.Column("public_id", sa.String(length=40), nullable=True))
    op.execute("UPDATE campaigns SET public_id = 'cmp_' || substr(replace(id::text, '-', ''), 1, 12) WHERE public_id IS NULL")
    op.alter_column("campaigns", "public_id", nullable=False)
    op.create_index("ix_campaigns_public_id", "campaigns", ["public_id"], unique=True)

    op.add_column("usage_ledger", sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("usage_ledger", sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("usage_ledger", sa.Column("provider_event_id", sa.String(length=255), nullable=True))
    op.create_foreign_key("fk_usage_ledger_message_id", "usage_ledger", "messages", ["message_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_usage_ledger_campaign_id", "usage_ledger", "campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_usage_ledger_message_id", "usage_ledger", ["message_id"])
    op.create_index("ix_usage_ledger_campaign_id", "usage_ledger", ["campaign_id"])
    op.create_index("ix_usage_ledger_provider_event_id", "usage_ledger", ["provider_event_id"])

    op.create_table(
        "onboarding_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.String(length=80), nullable=False),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_onboarding_status_events_business_id", "onboarding_status_events", ["business_id"])

    op.create_table(
        "subscription_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_status_events_subscription_id", "subscription_status_events", ["subscription_id"])

    op.create_table(
        "legal_holds",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("placed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["placed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_legal_holds_business_id", "legal_holds", ["business_id"])
    op.create_index("ix_legal_holds_entity_type", "legal_holds", ["entity_type"])
    op.create_index("ix_legal_holds_entity_id", "legal_holds", ["entity_id"])

    op.create_table(
        "impersonation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_impersonation_sessions_admin_user_id", "impersonation_sessions", ["admin_user_id"])
    op.create_index("ix_impersonation_sessions_business_id", "impersonation_sessions", ["business_id"])

    op.create_table(
        "api_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("environment", sa.String(length=20), nullable=False, server_default="live"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_clients_business_id", "api_clients", ["business_id"])

    op.create_table(
        "api_client_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["api_client_id"], ["api_clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_client_keys_api_client_id", "api_client_keys", ["api_client_id"])
    op.create_index("ix_api_client_keys_key_prefix", "api_client_keys", ["key_prefix"])
    op.create_index("uq_api_client_keys_key_hash", "api_client_keys", ["key_hash"], unique=True)

    op.create_table(
        "api_client_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["api_client_id"], ["api_clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_client_scopes_api_client_id", "api_client_scopes", ["api_client_id"])
    op.create_index("ix_api_client_scopes_scope", "api_client_scopes", ["scope"])

    op.create_table(
        "api_client_rate_limits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["api_client_id"], ["api_clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_client_rate_limits_api_client_id", "api_client_rate_limits", ["api_client_id"])
    op.create_index("ix_api_client_rate_limits_scope", "api_client_rate_limits", ["scope"])

    op.create_table(
        "customer_webhook_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("signing_secret_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("subscribed_events", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_webhook_endpoints_business_id", "customer_webhook_endpoints", ["business_id"])

    op.create_table(
        "customer_webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["endpoint_id"], ["customer_webhook_endpoints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_webhook_deliveries_endpoint_id", "customer_webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_customer_webhook_deliveries_event_type", "customer_webhook_deliveries", ["event_type"])
    op.create_index("ix_customer_webhook_deliveries_event_id", "customer_webhook_deliveries", ["event_id"])
    op.create_index("uq_customer_webhook_delivery_endpoint_event", "customer_webhook_deliveries", ["endpoint_id", "event_id"], unique=True)

    op.create_table(
        "customer_webhook_delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["delivery_id"], ["customer_webhook_deliveries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_webhook_delivery_attempts_delivery_id", "customer_webhook_delivery_attempts", ["delivery_id"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

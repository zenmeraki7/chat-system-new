"""Business identity and compliance operations

Revision ID: 007_business_identity_and_compliance_ops
Revises: 006_tenant_identity_and_ops_foundations
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007_business_identity_and_compliance_ops"
down_revision = "006_tenant_identity_and_ops_foundations"
branch_labels = None
depends_on = None


CORE_TABLES = [
    "businesses",
    "users",
    "roles",
    "permissions",
    "business_memberships",
    "membership_invites",
    "business_api_keys",
    "business_widget_settings",
    "business_ai_settings",
    "meta_business_accounts",
    "phone_number_assignments",
    "embedded_signup_sessions",
    "oauth_credentials",
    "whatsapp_business_accounts",
    "whatsapp_phone_numbers",
    "webhook_subscriptions",
    "webhook_events",
    "outbound_messages",
    "outbound_message_attempts",
    "message_status_events",
    "webhook_processing_attempts",
    "webhook_dead_letters",
    "campaigns",
    "campaign_recipient_snapshots",
    "usage_ledger",
    "billing_accounts",
    "business_compliance_profiles",
    "business_onboarding_steps",
    "email_verification_tokens",
    "password_reset_tokens",
    "user_sessions",
    "user_login_attempts",
    "identity_providers",
    "external_identities",
    "business_profiles",
    "subscriptions",
    "entitlements",
    "business_entitlements",
    "feature_flags",
    "business_feature_flags",
    "audit_logs",
]


def upgrade() -> None:
    op.add_column("businesses", sa.Column("slug", sa.String(length=120), nullable=True))
    op.add_column("businesses", sa.Column("public_id", sa.String(length=40), nullable=True))
    op.add_column("businesses", sa.Column("normalized_name", sa.String(length=255), nullable=True))
    op.execute("UPDATE businesses SET normalized_name = lower(trim(name)) WHERE normalized_name IS NULL")
    op.execute("UPDATE businesses SET slug = regexp_replace(normalized_name, '[^a-z0-9]+', '-', 'g') WHERE slug IS NULL")
    op.execute("UPDATE businesses SET public_id = 'biz_' || substr(replace(id::text, '-', ''), 1, 12) WHERE public_id IS NULL")
    op.alter_column("businesses", "slug", nullable=False)
    op.alter_column("businesses", "public_id", nullable=False)
    op.alter_column("businesses", "normalized_name", nullable=False)
    op.create_index("ix_businesses_slug", "businesses", ["slug"])
    op.create_index("ix_businesses_public_id", "businesses", ["public_id"], unique=True)
    op.create_index("ix_businesses_normalized_name", "businesses", ["normalized_name"])

    for table in CORE_TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])

    op.drop_index("uq_users_email_lower", table_name="users")
    op.create_index(
        "uq_users_email_active",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_business_slug_active",
        "businesses",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "business_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("reason_message", sa.Text(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_status_events_business_id", "business_status_events", ["business_id"])

    op.create_table(
        "whatsapp_asset_connection_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("asset_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meta_business_id", sa.String(length=255), nullable=True),
        sa.Column("raw_meta_response_ref", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whatsapp_asset_connection_events_asset_id", "whatsapp_asset_connection_events", ["asset_id"])

    op.create_table(
        "whatsapp_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="connected"),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
    )

    op.create_table(
        "business_legal_acceptances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("document_version", sa.String(length=80), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("whatsapp_business_accounts", sa.Column("review_status", sa.String(length=30), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("last_health_status", sa.String(length=30), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("last_health_error_code", sa.String(length=80), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("last_successful_send_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("last_webhook_received_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("last_template_sync_at", sa.DateTime(timezone=True), nullable=True))

    for table in ["whatsapp_phone_numbers", "oauth_credentials", "webhook_subscriptions"]:
        op.add_column(table, sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("last_health_status", sa.String(length=30), nullable=True))
        op.add_column(table, sa.Column("last_health_error_code", sa.String(length=80), nullable=True))
        op.add_column(table, sa.Column("last_successful_send_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("last_webhook_received_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("last_template_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("whatsapp_phone_numbers", sa.Column("sending_status", sa.String(length=30), nullable=True))

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_whatsapp_phone_numbers_display_phone_number
        ON whatsapp_phone_numbers (display_phone_number)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_business_api_keys_key_prefix
        ON business_api_keys (key_prefix)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_whatsapp_business_accounts_waba_id
        ON whatsapp_business_accounts (waba_id)
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")

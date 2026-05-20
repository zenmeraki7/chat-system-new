"""Provider retry/error ledgers, lifecycle fields, profile/theme versioning, and invariants foundations

Revision ID: 015_provider_retry_and_lifecycle
Revises: 014_billing_traceability_and_api_clients
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "015_provider_retry_and_lifecycle"
down_revision = "014_billing_traceability_and_api_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_rehash_required", sa.Boolean(), nullable=True))
    op.execute("UPDATE users SET password_rehash_required = false WHERE password_rehash_required IS NULL")
    op.alter_column("users", "password_rehash_required", nullable=False)

    op.execute("UPDATE users SET email = lower(trim(email)) WHERE email IS NOT NULL")
    op.create_index(
        "uq_users_email_lower_active",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column("business_api_keys", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("whatsapp_phone_numbers", sa.Column("status", sa.String(length=30), nullable=True))
    op.execute("UPDATE whatsapp_phone_numbers SET status = 'active' WHERE status IS NULL")
    op.alter_column("whatsapp_phone_numbers", "status", nullable=False)
    op.add_column("whatsapp_phone_numbers", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("webhook_subscriptions", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("webhook_events", sa.Column("status", sa.String(length=30), nullable=True))
    op.execute("UPDATE webhook_events SET status = 'received' WHERE status IS NULL")
    op.alter_column("webhook_events", "status", nullable=False)

    op.add_column("campaigns", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("contacts", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("contacts", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("conversations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("messages", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("customer_webhook_endpoints", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "provider_request_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("external_asset_id", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("provider_error_code", sa.String(length=80), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_request_logs_business_id", "provider_request_logs", ["business_id"])
    op.create_index("ix_provider_request_logs_provider", "provider_request_logs", ["provider"])
    op.create_index("ix_provider_request_logs_operation", "provider_request_logs", ["operation"])
    op.create_index("ix_provider_request_logs_external_asset_id", "provider_request_logs", ["external_asset_id"])
    op.create_index("ix_provider_request_logs_request_id", "provider_request_logs", ["request_id"])
    op.create_index("ix_provider_request_logs_provider_error_code", "provider_request_logs", ["provider_error_code"])

    op.create_table(
        "provider_error_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=False),
        sa.Column("error_subcode", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("retry_policy", sa.String(length=40), nullable=False),
        sa.Column("user_visible_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_error_mappings_provider", "provider_error_mappings", ["provider"])
    op.create_index("ix_provider_error_mappings_error_code", "provider_error_mappings", ["error_code"])
    op.create_index("ix_provider_error_mappings_error_subcode", "provider_error_mappings", ["error_subcode"])
    op.create_index("uq_provider_error_mapping", "provider_error_mappings", ["provider", "error_code", "error_subcode"], unique=True)

    op.create_table(
        "business_profile_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("support_email", sa.String(length=255), nullable=True),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_profile_versions_business_id", "business_profile_versions", ["business_id"])

    op.create_table(
        "widget_theme_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_widget_theme_presets_name", "widget_theme_presets", ["name"], unique=True)

    op.add_column("business_widget_settings", sa.Column("widget_theme_preset_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_business_widget_settings_widget_theme_preset_id",
        "business_widget_settings",
        "widget_theme_presets",
        ["widget_theme_preset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_business_widget_settings_widget_theme_preset_id", "business_widget_settings", ["widget_theme_preset_id"])

    op.create_table(
        "brand_widget_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("widget_theme_preset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("widget_color", sa.String(length=20), nullable=False, server_default="#6366f1"),
        sa.Column("widget_title", sa.String(length=100), nullable=False, server_default="Chat with us"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["widget_theme_preset_id"], ["widget_theme_presets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_brand_widget_settings_brand_id", "brand_widget_settings", ["brand_id"], unique=True)
    op.create_index("ix_brand_widget_settings_widget_theme_preset_id", "brand_widget_settings", ["widget_theme_preset_id"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

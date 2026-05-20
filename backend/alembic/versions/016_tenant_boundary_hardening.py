"""Tenant boundary hardening, provider asset mapping, credential lineage, and operational locks

Revision ID: 016_tenant_boundary_hardening
Revises: 015_provider_retry_and_lifecycle
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "016_tenant_boundary_hardening"
down_revision = "015_provider_retry_and_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_credentials", sa.Column("grant_type", sa.String(length=50), nullable=True))
    op.add_column("oauth_credentials", sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("oauth_credentials", sa.Column("provider_subject_id", sa.String(length=255), nullable=True))
    op.add_column("oauth_credentials", sa.Column("credential_purpose", sa.String(length=80), nullable=True))
    op.add_column("oauth_credentials", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_credentials", sa.Column("last_used_ip", sa.String(length=64), nullable=True))
    op.add_column("oauth_credentials", sa.Column("last_used_service", sa.String(length=80), nullable=True))
    op.create_foreign_key("fk_oauth_credentials_granted_by_user_id", "oauth_credentials", "users", ["granted_by_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_oauth_credentials_granted_by_user_id", "oauth_credentials", ["granted_by_user_id"])
    op.create_index("ix_oauth_credentials_provider_subject_id", "oauth_credentials", ["provider_subject_id"])

    op.add_column("provider_request_logs", sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_provider_request_logs_credential_id", "provider_request_logs", "oauth_credentials", ["credential_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_provider_request_logs_credential_id", "provider_request_logs", ["credential_id"])

    op.add_column("whatsapp_phone_numbers", sa.Column("is_default_for_sending", sa.Boolean(), nullable=True))
    op.add_column("whatsapp_phone_numbers", sa.Column("is_default_for_inbox", sa.Boolean(), nullable=True))
    op.execute("UPDATE whatsapp_phone_numbers SET is_default_for_sending = false WHERE is_default_for_sending IS NULL")
    op.execute("UPDATE whatsapp_phone_numbers SET is_default_for_inbox = false WHERE is_default_for_inbox IS NULL")
    op.alter_column("whatsapp_phone_numbers", "is_default_for_sending", nullable=False)
    op.alter_column("whatsapp_phone_numbers", "is_default_for_inbox", nullable=False)
    op.create_index(
        "uq_one_default_sending_number",
        "whatsapp_phone_numbers",
        ["business_id"],
        unique=True,
        postgresql_where=sa.text("is_default_for_sending = true AND status = 'active' AND disconnected_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_one_default_inbox_number",
        "whatsapp_phone_numbers",
        ["business_id"],
        unique=True,
        postgresql_where=sa.text("is_default_for_inbox = true AND status = 'active' AND disconnected_at IS NULL AND deleted_at IS NULL"),
    )

    op.add_column("contacts", sa.Column("raw_phone", sa.String(length=50), nullable=True))
    op.add_column("contacts", sa.Column("normalized_phone", sa.String(length=20), nullable=True))
    op.add_column("contacts", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.add_column("contacts", sa.Column("phone_hash", sa.String(length=128), nullable=True))
    op.create_index("ix_contacts_normalized_phone", "contacts", ["normalized_phone"])
    op.create_index("ix_contacts_phone_hash", "contacts", ["phone_hash"])
    op.create_index(
        "uq_contact_phone_per_business",
        "contacts",
        ["business_id", "normalized_phone"],
        unique=True,
        postgresql_where=sa.text("normalized_phone IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_contact_phone_identity",
        "contact_identities",
        ["business_id", "identity_type", "identity_value_hash"],
        unique=True,
        postgresql_where=sa.text("identity_type = 'phone' AND deleted_at IS NULL"),
    )

    op.create_index(
        "uq_campaign_name_optional",
        "campaigns",
        ["business_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_index(
        "uq_template_per_waba",
        "whatsapp_message_templates",
        ["business_id", "waba_id", "name", "language"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "business_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_widget_settings_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_ai_settings_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["active_widget_settings_version_id"], ["widget_setting_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["active_ai_settings_version_id"], ["business_ai_setting_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_business_settings_business_id", "business_settings", ["business_id"], unique=True)
    op.create_index("ix_business_settings_active_widget_settings_version_id", "business_settings", ["active_widget_settings_version_id"])
    op.create_index("ix_business_settings_active_ai_settings_version_id", "business_settings", ["active_ai_settings_version_id"])

    op.create_table(
        "provider_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_accounts_business_id", "provider_accounts", ["business_id"])
    op.create_index("ix_provider_accounts_provider", "provider_accounts", ["provider"])
    op.create_index("ix_provider_accounts_external_account_id", "provider_accounts", ["external_account_id"])
    op.create_index("uq_provider_account_per_business", "provider_accounts", ["business_id", "provider", "external_account_id"], unique=True)

    op.create_table(
        "business_provider_asset_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_status", sa.String(length=30), nullable=False, server_default="linked"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_method", sa.String(length=80), nullable=True),
        sa.Column("verified_by_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_asset_id"], ["provider_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by_credential_id"], ["oauth_credentials.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_provider_asset_links_business_id", "business_provider_asset_links", ["business_id"])
    op.create_index("ix_business_provider_asset_links_provider_asset_id", "business_provider_asset_links", ["provider_asset_id"])
    op.create_index("ix_business_provider_asset_links_verified_by_credential_id", "business_provider_asset_links", ["verified_by_credential_id"])
    op.create_index("uq_business_provider_asset_link", "business_provider_asset_links", ["business_id", "provider_asset_id"], unique=True)

    op.create_table(
        "operation_locks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lock_name", sa.String(length=120), nullable=False),
        sa.Column("owner_token", sa.String(length=120), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operation_locks_business_id", "operation_locks", ["business_id"])
    op.create_index("ix_operation_locks_owner_token", "operation_locks", ["owner_token"])
    op.create_index("ix_operation_locks_expires_at", "operation_locks", ["expires_at"])
    op.create_index(
        "uq_operation_lock_active",
        "operation_locks",
        ["business_id", "lock_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.execute(
        """
        UPDATE messages m
        SET business_id = c.business_id
        FROM conversations c
        WHERE m.conversation_id = c.id
          AND m.business_id IS NULL
        """
    )
    op.alter_column("messages", "business_id", nullable=False)
    op.create_index("uq_conversations_business_id_id", "conversations", ["business_id", "id"], unique=True)
    op.create_foreign_key(
        "fk_messages_conversation_tenant",
        "messages",
        "conversations",
        ["business_id", "conversation_id"],
        ["business_id", "id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

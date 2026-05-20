"""Message domain explicit columns, sender/recipient linkage, and send-attempt ledger

Revision ID: 020_message_domain_explicit_fields
Revises: 019_message_and_conversation_boundary_hardening
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "020_message_domain_explicit_fields"
down_revision = "019_message_and_conversation_boundary_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("campaign_recipient_snapshot_item_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("template_name", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("template_language", sa.String(length=20), nullable=True))
    op.add_column("messages", sa.Column("template_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.add_column("messages", sa.Column("sender_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("bot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("api_client_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.add_column("messages", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("received_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True))

    op.add_column("messages", sa.Column("failure_code", sa.String(length=120), nullable=True))
    op.add_column("messages", sa.Column("failure_message", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("failure_source", sa.String(length=80), nullable=True))
    op.add_column("messages", sa.Column("retryable", sa.Boolean(), nullable=True))

    op.add_column("messages", sa.Column("provider_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_foreign_key("fk_messages_channel_id", "messages", "channels", ["channel_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_messages_contact_id", "messages", "contacts", ["contact_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_messages_campaign_id", "messages", "campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_messages_campaign_recipient_snapshot_item_id",
        "messages",
        "campaign_recipient_snapshot_items",
        ["campaign_recipient_snapshot_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key("fk_messages_template_id", "messages", "whatsapp_message_templates", ["template_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_messages_template_snapshot_id", "messages", "campaign_approval_snapshots", ["template_snapshot_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_messages_media_asset_id", "messages", "media_assets", ["media_asset_id"], ["id"], ondelete="SET NULL")

    op.create_foreign_key("fk_messages_sender_user_id", "messages", "users", ["sender_user_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_messages_bot_id", "messages", "bots", ["bot_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_messages_api_client_id", "messages", "api_clients", ["api_client_id"], ["id"], ondelete="SET NULL")

    op.create_index("ix_messages_channel_id", "messages", ["channel_id"])
    op.create_index("ix_messages_contact_id", "messages", ["contact_id"])
    op.create_index("ix_messages_campaign_id", "messages", ["campaign_id"])
    op.create_index("ix_messages_template_id", "messages", ["template_id"])
    op.create_index("ix_messages_media_asset_id", "messages", ["media_asset_id"])

    op.execute("UPDATE messages SET queued_at = created_at WHERE queued_at IS NULL")

    op.create_table(
        "message_send_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("request_correlation_id", sa.String(length=120), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("provider_error_code", sa.String(length=120), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_send_attempts_business_id", "message_send_attempts", ["business_id"])
    op.create_index("ix_message_send_attempts_message_id", "message_send_attempts", ["message_id"])

    op.create_table(
        "whatsapp_message_metadata",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number_id", sa.String(length=255), nullable=True),
        sa.Column("customer_wa_id", sa.String(length=255), nullable=True),
        sa.Column("waba_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_whatsapp_message_metadata_message_id", "whatsapp_message_metadata", ["message_id"], unique=True)

    op.create_index(
        "uq_message_status_event_dedupe",
        "message_status_events",
        ["business_id", "provider_status", "provider_timestamp", "message_id"],
        unique=True,
        postgresql_where=sa.text("provider_status IS NOT NULL AND provider_timestamp IS NOT NULL AND message_id IS NOT NULL"),
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

"""Message outbox, webhook status event shape, and billing ledger

Revision ID: 033_message_outbox_status_events_and_billing_ledger
Revises: 032_campaign_recipient_events_and_send_jobs
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "033_message_outbox_status_events_and_billing_ledger"
down_revision = "032_campaign_recipient_events_and_send_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_recipient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_number_id", sa.String(length=255), nullable=False),
        sa.Column("to_phone_e164", sa.String(length=20), nullable=False),
        sa.Column("message_type", sa.String(length=40), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["campaign_recipient_id"], ["campaign_recipients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["whatsapp_message_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_message_outbox_idempotency_key"),
    )
    op.create_index("ix_message_outbox_business_id", "message_outbox", ["business_id"])
    op.create_index("ix_message_outbox_campaign_id", "message_outbox", ["campaign_id"])
    op.create_index("ix_message_outbox_campaign_recipient_id", "message_outbox", ["campaign_recipient_id"])
    op.create_index("ix_message_outbox_phone_number_id", "message_outbox", ["phone_number_id"])
    op.create_index("ix_message_outbox_to_phone_e164", "message_outbox", ["to_phone_e164"])
    op.create_index("ix_message_outbox_status", "message_outbox", ["status"])
    op.create_index("ix_message_outbox_provider_message_id", "message_outbox", ["provider_message_id"])
    op.create_index("ix_message_outbox_next_retry_at", "message_outbox", ["next_retry_at"])

    op.add_column("message_status_events", sa.Column("phone_number_id", sa.String(length=255), nullable=True))
    op.add_column("message_status_events", sa.Column("provider_message_id", sa.String(length=255), nullable=True))
    op.add_column("message_status_events", sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True))
    op.add_column("message_status_events", sa.Column("pricing_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("message_status_events", sa.Column("conversation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("message_status_events", sa.Column("errors_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index("ix_message_status_events_phone_number_id", "message_status_events", ["phone_number_id"])
    op.create_index("ix_message_status_events_provider_message_id", "message_status_events", ["provider_message_id"])
    op.create_index("ix_message_status_events_timestamp", "message_status_events", ["timestamp"])
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mse_provider_message_status_timestamp
        ON message_status_events (provider_message_id, status, "timestamp")
        WHERE provider_message_id IS NOT NULL AND "timestamp" IS NOT NULL
        """
    )

    op.create_table(
        "billing_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_recipient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_outbox_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("entry_type", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="posted"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["campaign_recipient_id"], ["campaign_recipients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_outbox_id"], ["message_outbox.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_ledger_business_id", "billing_ledger", ["business_id"])
    op.create_index("ix_billing_ledger_campaign_id", "billing_ledger", ["campaign_id"])
    op.create_index("ix_billing_ledger_campaign_recipient_id", "billing_ledger", ["campaign_recipient_id"])
    op.create_index("ix_billing_ledger_message_outbox_id", "billing_ledger", ["message_outbox_id"])
    op.create_index("ix_billing_ledger_provider_message_id", "billing_ledger", ["provider_message_id"])
    op.create_index("ix_billing_ledger_entry_type", "billing_ledger", ["entry_type"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")

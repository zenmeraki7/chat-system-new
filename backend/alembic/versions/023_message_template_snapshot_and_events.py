"""Message template snapshot, campaign snapshot linkage, policy/pricing links, and event tables

Revision ID: 023_message_template_snapshot_and_events
Revises: 022_message_reliability_and_correlation
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "023_message_template_snapshot_and_events"
down_revision = "022_message_reliability_and_correlation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE messages RENAME COLUMN campaign_recipient_snapshot_item_id TO campaign_snapshot_item_id"
    )

    op.drop_constraint("fk_messages_campaign_recipient_snapshot_item_id", "messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_messages_campaign_snapshot_item_id",
        "messages",
        "campaign_recipient_snapshot_items",
        ["campaign_snapshot_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute("DROP INDEX IF EXISTS uq_campaign_snapshot_item_message")
    op.create_index(
        "uq_campaign_snapshot_item_message",
        "messages",
        ["business_id", "campaign_snapshot_item_id"],
        unique=True,
        postgresql_where=sa.text("campaign_snapshot_item_id IS NOT NULL"),
    )

    op.add_column("messages", sa.Column("campaign_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("template_category", sa.String(length=60), nullable=True))
    op.add_column("messages", sa.Column("template_components_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("messages", sa.Column("template_variables_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("messages", sa.Column("rendered_preview_text", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("opt_in_evidence_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("send_policy_decision_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("billing_classification_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("conversation_pricing_window_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("usage_ledger_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("interactive_type", sa.String(length=60), nullable=True))
    op.add_column("messages", sa.Column("interactive_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("messages", sa.Column("selected_button_id", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("selected_list_row_id", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("location_latitude", sa.Float(), nullable=True))
    op.add_column("messages", sa.Column("location_longitude", sa.Float(), nullable=True))
    op.add_column("messages", sa.Column("reaction_to_provider_message_id", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("referral_source_url", sa.String(length=1024), nullable=True))
    op.add_column("messages", sa.Column("unsupported_reason", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("source_type", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("source_id", sa.String(length=255), nullable=True))

    op.create_foreign_key(
        "fk_messages_campaign_snapshot_id",
        "messages",
        "campaign_recipient_snapshots",
        ["campaign_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_messages_opt_in_evidence_id",
        "messages",
        "compliance_evidence",
        ["opt_in_evidence_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_messages_billing_classification_id",
        "messages",
        "message_price_rules",
        ["billing_classification_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_messages_usage_ledger_id",
        "messages",
        "usage_ledger",
        ["usage_ledger_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "send_policy_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.String(length=255), nullable=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False, server_default="allow"),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_send_policy_decisions_business_id", "send_policy_decisions", ["business_id"])
    op.create_index("ix_send_policy_decisions_contact_id", "send_policy_decisions", ["contact_id"])
    op.create_index("ix_send_policy_decisions_channel_id", "send_policy_decisions", ["channel_id"])

    op.create_table(
        "whatsapp_pricing_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number_id", sa.String(length=255), nullable=False),
        sa.Column("customer_wa_id", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_by_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["opened_by_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whatsapp_pricing_windows_business_id", "whatsapp_pricing_windows", ["business_id"])
    op.create_index("ix_whatsapp_pricing_windows_phone_number_id", "whatsapp_pricing_windows", ["phone_number_id"])
    op.create_index("ix_whatsapp_pricing_windows_customer_wa_id", "whatsapp_pricing_windows", ["customer_wa_id"])
    op.create_index("ix_whatsapp_pricing_windows_opened_by_message_id", "whatsapp_pricing_windows", ["opened_by_message_id"])

    op.create_table(
        "message_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_events_business_id", "message_events", ["business_id"])
    op.create_index("ix_message_events_message_id", "message_events", ["message_id"])
    op.create_index("ix_message_events_event_type", "message_events", ["event_type"])

    op.create_foreign_key(
        "fk_messages_send_policy_decision_id",
        "messages",
        "send_policy_decisions",
        ["send_policy_decision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_messages_conversation_pricing_window_id",
        "messages",
        "whatsapp_pricing_windows",
        ["conversation_pricing_window_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_messages_campaign_snapshot_id", "messages", ["campaign_snapshot_id"])
    op.create_index("ix_messages_opt_in_evidence_id", "messages", ["opt_in_evidence_id"])
    op.create_index("ix_messages_send_policy_decision_id", "messages", ["send_policy_decision_id"])
    op.create_index("ix_messages_billing_classification_id", "messages", ["billing_classification_id"])
    op.create_index("ix_messages_conversation_pricing_window_id", "messages", ["conversation_pricing_window_id"])
    op.create_index("ix_messages_usage_ledger_id", "messages", ["usage_ledger_id"])
    op.create_index("ix_messages_selected_button_id", "messages", ["selected_button_id"])
    op.create_index("ix_messages_selected_list_row_id", "messages", ["selected_list_row_id"])
    op.create_index("ix_messages_reaction_to_provider_message_id", "messages", ["reaction_to_provider_message_id"])
    op.create_index("ix_messages_source_type", "messages", ["source_type"])
    op.create_index("ix_messages_source_id", "messages", ["source_id"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

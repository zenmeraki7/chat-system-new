"""Campaign lifecycle columns and campaign_recipients table

Revision ID: 031_campaign_lifecycle_tables
Revises: 030_contact_hygiene_fields
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "031_campaign_lifecycle_tables"
down_revision = "030_contact_hygiene_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("waba_id", sa.String(length=255), nullable=True))
    op.add_column("campaigns", sa.Column("phone_number_id", sa.String(length=255), nullable=True))
    op.add_column("campaigns", sa.Column("type", sa.String(length=40), nullable=False, server_default="broadcast"))
    op.add_column("campaigns", sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("campaigns", sa.Column("template_name", sa.String(length=255), nullable=True))
    op.add_column("campaigns", sa.Column("template_language", sa.String(length=20), nullable=True))
    op.add_column("campaigns", sa.Column("template_category", sa.String(length=60), nullable=True))
    op.add_column("campaigns", sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("campaigns", sa.Column("csv_import_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("campaigns", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("campaigns", sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("eligible_recipients", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("skipped_recipients", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("replied_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaigns", sa.Column("estimated_cost", sa.Numeric(12, 4), nullable=True))
    op.add_column("campaigns", sa.Column("reserved_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("campaigns", sa.Column("actual_cost", sa.Numeric(12, 4), nullable=True))

    op.create_foreign_key("fk_campaigns_template_id", "campaigns", "whatsapp_message_templates", ["template_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_campaigns_segment_id", "campaigns", "conversation_saved_views", ["segment_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_campaigns_csv_import_id", "campaigns", "contact_import_jobs", ["csv_import_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_campaigns_created_by_user_id", "campaigns", "users", ["created_by_user_id"], ["id"], ondelete="SET NULL")

    op.create_index("ix_campaigns_business_status", "campaigns", ["business_id", "status"])
    op.create_index("ix_campaigns_business_phone_status", "campaigns", ["business_id", "phone_number_id", "status"])
    op.create_index("ix_campaigns_scheduled_status", "campaigns", ["scheduled_at", "status"])

    op.create_table(
        "campaign_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("wa_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("eligibility_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("eligibility_reason", sa.Text(), nullable=True),
        sa.Column("variables_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rendered_template_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(12, 4), nullable=True),
        sa.Column("reserved_amount", sa.Numeric(12, 4), nullable=True),
        sa.Column("actual_cost", sa.Numeric(12, 4), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "phone_e164", name="uq_campaign_recipients_campaign_phone"),
    )
    op.create_index("ix_campaign_recipients_campaign_status", "campaign_recipients", ["campaign_id", "status"])
    op.create_index("ix_campaign_recipients_business_phone", "campaign_recipients", ["business_id", "phone_e164"])
    op.create_index("ix_campaign_recipients_provider_message_id", "campaign_recipients", ["provider_message_id"])
    op.create_index("ix_campaign_recipients_next_retry_status", "campaign_recipients", ["next_retry_at", "status"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")

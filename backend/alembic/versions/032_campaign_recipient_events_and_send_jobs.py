"""Campaign recipient events and send jobs

Revision ID: 032_campaign_recipient_events_and_send_jobs
Revises: 031_campaign_lifecycle_tables
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "032_campaign_recipient_events_and_send_jobs"
down_revision = "031_campaign_lifecycle_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_recipient_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_recipient_id"], ["campaign_recipients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_recipient_events_campaign_id", "campaign_recipient_events", ["campaign_id"])
    op.create_index("ix_campaign_recipient_events_recipient_id", "campaign_recipient_events", ["campaign_recipient_id"])
    op.create_index("ix_campaign_recipient_events_business_id", "campaign_recipient_events", ["business_id"])
    op.create_index("ix_campaign_recipient_events_event_type", "campaign_recipient_events", ["event_type"])
    op.create_index("ix_campaign_recipient_events_provider_message_id", "campaign_recipient_events", ["provider_message_id"])

    op.create_table(
        "campaign_send_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_recipient_id"], ["campaign_recipients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_send_jobs_campaign_status", "campaign_send_jobs", ["campaign_id", "status"])
    op.create_index("ix_campaign_send_jobs_business_schedule_status", "campaign_send_jobs", ["business_id", "scheduled_at", "status"])
    op.create_index("ix_campaign_send_jobs_phone_status", "campaign_send_jobs", ["phone_number_id", "status"])
    op.create_index("ix_campaign_send_jobs_locked_until", "campaign_send_jobs", ["locked_until"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")

"""campaign black box execution events

Revision ID: 041_campaign_black_box_execution_events
Revises: 040_outbox_campaign_id_and_finalize_sweep_indexes
Create Date: 2026-05-20 23:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "041_campaign_black_box_execution_events"
down_revision = "040_outbox_campaign_id_and_finalize_sweep_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_execution_events",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_execution_events_campaign_id", "campaign_execution_events", ["campaign_id"], unique=False)
    op.create_index("ix_campaign_execution_events_business_id", "campaign_execution_events", ["business_id"], unique=False)
    op.create_index("ix_campaign_execution_events_event_type", "campaign_execution_events", ["event_type"], unique=False)
    op.create_index("ix_campaign_execution_events_observed_at", "campaign_execution_events", ["observed_at"], unique=False)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_campaign_execution_events_timeline
        ON campaign_execution_events (business_id, campaign_id, observed_at DESC, id DESC)
        WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_campaign_execution_events_timeline")
    op.drop_index("ix_campaign_execution_events_observed_at", table_name="campaign_execution_events")
    op.drop_index("ix_campaign_execution_events_event_type", table_name="campaign_execution_events")
    op.drop_index("ix_campaign_execution_events_business_id", table_name="campaign_execution_events")
    op.drop_index("ix_campaign_execution_events_campaign_id", table_name="campaign_execution_events")
    op.drop_table("campaign_execution_events")

"""outbox campaign id and finalize sweep indexes

Revision ID: 040_outbox_campaign_id_and_finalize_sweep_indexes
Revises: 039_worker_hotpath_indexes_and_finalize_debounce_support
Create Date: 2026-05-20 23:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "040_outbox_campaign_id_and_finalize_sweep_indexes"
down_revision = "039_worker_hotpath_indexes_and_finalize_debounce_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_outbox_events_campaign_id",
        "outbox_events",
        "campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_outbox_events_campaign_id", "outbox_events", ["campaign_id"], unique=False)

    op.execute(
        """
        UPDATE outbox_events
        SET campaign_id = NULLIF(payload_json->>'campaign_id', '')::uuid
        WHERE campaign_id IS NULL
          AND payload_json ? 'campaign_id'
          AND (payload_json->>'campaign_id') ~* '^[0-9a-f-]{36}$'
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_outbox_events_campaign_finalize_pending
        ON outbox_events (campaign_id, status, available_at, created_at, id)
        WHERE event_type = 'campaign.finalize' AND deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_campaign_active_for_finalize_sweep
        ON campaigns (status, updated_at, id)
        WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_campaign_active_for_finalize_sweep")
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_campaign_finalize_pending")
    op.drop_index("ix_outbox_events_campaign_id", table_name="outbox_events")
    op.drop_constraint("fk_outbox_events_campaign_id", "outbox_events", type_="foreignkey")
    op.drop_column("outbox_events", "campaign_id")

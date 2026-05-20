"""message outbox source priority schedule

Revision ID: 042_message_outbox_source_priority_schedule
Revises: 041_campaign_black_box_execution_events
Create Date: 2026-05-21 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "042_message_outbox_source_priority_schedule"
down_revision = "041_campaign_black_box_execution_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("message_outbox", sa.Column("source_type", sa.String(length=40), nullable=False, server_default="unknown"))
    op.add_column("message_outbox", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("message_outbox", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))

    op.create_index("ix_message_outbox_source_type", "message_outbox", ["source_type"], unique=False)
    op.create_index("ix_message_outbox_priority", "message_outbox", ["priority"], unique=False)
    op.create_index("ix_message_outbox_scheduled_at", "message_outbox", ["scheduled_at"], unique=False)

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_message_outbox_priority_queue_poll
        ON message_outbox (status, scheduled_at, priority, created_at, id)
        WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_outbox_priority_queue_poll")
    op.drop_index("ix_message_outbox_scheduled_at", table_name="message_outbox")
    op.drop_index("ix_message_outbox_priority", table_name="message_outbox")
    op.drop_index("ix_message_outbox_source_type", table_name="message_outbox")
    op.drop_column("message_outbox", "scheduled_at")
    op.drop_column("message_outbox", "priority")
    op.drop_column("message_outbox", "source_type")

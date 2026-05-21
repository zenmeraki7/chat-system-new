"""Outbox regional routing and workload class metadata

Revision ID: 047_outbox_regional_isolation_and_workload_class
Revises: 046_contact_export_jobs_and_query_snapshots
Create Date: 2026-05-20 11:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "047_outbox_regional_isolation_and_workload_class"
down_revision = "046_contact_export_jobs_and_query_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("queue_region", sa.String(length=16), nullable=False, server_default="global"))
    op.add_column("outbox_events", sa.Column("queue_domain", sa.String(length=40), nullable=False, server_default="generic"))
    op.add_column("outbox_events", sa.Column("workload_class", sa.String(length=20), nullable=False, server_default="cold"))
    op.add_column("outbox_events", sa.Column("trace_id", sa.String(length=120), nullable=True))

    op.execute(
        """
        UPDATE outbox_events
        SET workload_class = CASE
            WHEN event_type LIKE 'webhook.%' THEN 'hot'
            WHEN event_type IN ('whatsapp.send.outbound', 'campaign_dispatch_job', 'campaign_batch_dispatch_job') THEN 'hot'
            WHEN event_type LIKE 'conversation.%' THEN 'hot'
            ELSE 'cold'
        END,
        queue_domain = CASE
            WHEN event_type LIKE 'webhook.%' THEN 'webhooks'
            WHEN event_type IN ('whatsapp.send.outbound') THEN 'send'
            WHEN event_type LIKE 'conversation.%' THEN 'inbox'
            WHEN event_type LIKE 'campaign.%' OR event_type LIKE 'bulk_job.%' THEN 'campaign'
            WHEN event_type LIKE 'contact_export.%' THEN 'exports'
            ELSE 'generic'
        END
        """
    )

    op.create_index("ix_outbox_events_queue_region", "outbox_events", ["queue_region"])
    op.create_index("ix_outbox_events_queue_domain", "outbox_events", ["queue_domain"])
    op.create_index("ix_outbox_events_workload_class", "outbox_events", ["workload_class"])
    op.create_index("ix_outbox_events_trace_id", "outbox_events", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_trace_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_workload_class", table_name="outbox_events")
    op.drop_index("ix_outbox_events_queue_domain", table_name="outbox_events")
    op.drop_index("ix_outbox_events_queue_region", table_name="outbox_events")
    op.drop_column("outbox_events", "trace_id")
    op.drop_column("outbox_events", "workload_class")
    op.drop_column("outbox_events", "queue_domain")
    op.drop_column("outbox_events", "queue_region")

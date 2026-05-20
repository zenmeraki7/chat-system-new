"""worker hotpath indexes and finalize debounce support

Revision ID: 039_worker_hotpath_indexes_and_finalize_debounce_support
Revises: 038_campaign_preview_and_config_hash
Create Date: 2026-05-20 22:40:00.000000
"""

from alembic import op


revision = "039_worker_hotpath_indexes_and_finalize_debounce_support"
down_revision = "038_campaign_preview_and_config_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Outbox worker polling: event_type + status + available_at + created_at.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_outbox_events_worker_poll
        ON outbox_events (event_type, status, available_at, created_at, id)
        WHERE deleted_at IS NULL
        """
    )

    # Campaign finalize dedupe lookup by campaign id in payload JSON.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_outbox_events_campaign_finalize_campaign_id
        ON outbox_events ((payload_json ->> 'campaign_id'))
        WHERE event_type = 'campaign.finalize' AND status = 'pending' AND deleted_at IS NULL
        """
    )

    # Message send worker polling.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_message_outbox_send_poll
        ON message_outbox (status, next_retry_at, created_at, id)
        WHERE deleted_at IS NULL
        """
    )

    # Webhook status lookup from provider_message_id -> outbox row.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_message_outbox_provider_lookup
        ON message_outbox (provider_message_id, created_at, id)
        WHERE deleted_at IS NULL AND provider_message_id IS NOT NULL
        """
    )

    # Campaign batch dispatch recipient scan.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_campaign_recipients_dispatch_scan
        ON campaign_recipients (campaign_id, business_id, eligibility_status, status, id)
        WHERE deleted_at IS NULL
        """
    )

    # Webhook status dedupe scan.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_message_status_events_dedupe_lookup
        ON message_status_events (provider_message_id, status, timestamp)
        WHERE deleted_at IS NULL AND provider_message_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_status_events_dedupe_lookup")
    op.execute("DROP INDEX IF EXISTS ix_campaign_recipients_dispatch_scan")
    op.execute("DROP INDEX IF EXISTS ix_message_outbox_provider_lookup")
    op.execute("DROP INDEX IF EXISTS ix_message_outbox_send_poll")
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_campaign_finalize_campaign_id")
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_worker_poll")

"""add cursor pagination support indexes

Revision ID: 048_cursor_pagination_indexes
Revises: 047_outbox_regional_isolation_and_workload_class
Create Date: 2026-05-21
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "048_cursor_pagination_indexes"
down_revision = "047_outbox_regional_isolation_and_workload_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_business_updated_id
            ON contacts (business_id, updated_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_business_created_id
            ON contacts (business_id, created_at DESC, id DESC)
            """
        )
        # Schema uses normalized_phone (not phone_number).
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_contacts_business_phone
            ON contacts (business_id, normalized_phone)
            """
        )

        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_business_updated_id
            ON conversations (business_id, updated_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_business_status_updated_id
            ON conversations (business_id, status, updated_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversations_business_assignee_updated_id
            ON conversations (business_id, assigned_user_id, updated_at DESC, id DESC)
            """
        )

        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_business_conversation_created_id
            ON messages (business_id, conversation_id, created_at DESC, id DESC)
            """
        )
        # Schema uses provider_message_id (provider authoritative message id).
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_business_whatsapp_message_id
            ON messages (business_id, provider_message_id)
            """
        )

        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_recipients_campaign_status_id
            ON campaign_recipients (campaign_id, status, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_campaign_recipients_business_campaign_id
            ON campaign_recipients (business_id, campaign_id, id DESC)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_recipients_business_campaign_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_campaign_recipients_campaign_status_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_messages_business_whatsapp_message_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_messages_business_conversation_created_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_conversations_business_assignee_updated_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_conversations_business_status_updated_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_conversations_business_updated_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_business_phone")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_business_created_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_contacts_business_updated_id")

"""Message tenant-safe composite keys and provider acceptance timestamp

Revision ID: 025_message_tenant_fk_and_provider_accepted_at
Revises: 024_message_provenance_and_moderation
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa


revision = "025_message_tenant_fk_and_provider_accepted_at"
down_revision = "024_message_provenance_and_moderation"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("messages", sa.Column("provider_accepted_at", sa.DateTime(timezone=True), nullable=True))

    op.create_unique_constraint(
        "uq_messages_business_id_id",
        "messages",
        ["business_id", "id"],
    )

    op.execute("ALTER TABLE message_send_attempts DROP CONSTRAINT IF EXISTS message_send_attempts_message_id_fkey")
    op.create_foreign_key(
        "fk_message_send_attempts_message_tenant",
        "message_send_attempts",
        "messages",
        ["business_id", "message_id"],
        ["business_id", "id"],
        ondelete="RESTRICT",
    )

    op.execute("ALTER TABLE message_events DROP CONSTRAINT IF EXISTS message_events_message_id_fkey")
    op.create_foreign_key(
        "fk_message_events_message_tenant",
        "message_events",
        "messages",
        ["business_id", "message_id"],
        ["business_id", "id"],
        ondelete="RESTRICT",
    )

    op.execute("ALTER TABLE message_moderation_results DROP CONSTRAINT IF EXISTS message_moderation_results_message_id_fkey")
    op.create_foreign_key(
        "fk_message_moderation_results_message_tenant",
        "message_moderation_results",
        "messages",
        ["business_id", "message_id"],
        ["business_id", "id"],
        ondelete="RESTRICT",
    )

    op.execute("ALTER TABLE message_search_documents DROP CONSTRAINT IF EXISTS message_search_documents_message_id_fkey")
    op.create_foreign_key(
        "fk_message_search_documents_message_tenant",
        "message_search_documents",
        "messages",
        ["business_id", "message_id"],
        ["business_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

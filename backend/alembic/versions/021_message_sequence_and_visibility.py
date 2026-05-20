"""Message sequencing, attempts ledger hardening, visibility, redaction, and moderation fields

Revision ID: 021_message_sequence_and_visibility
Revises: 020_message_domain_explicit_fields
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "021_message_sequence_and_visibility"
down_revision = "020_message_domain_explicit_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 22: deterministic conversation sequence
    op.add_column("messages", sa.Column("conversation_sequence", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY business_id, conversation_id
                       ORDER BY COALESCE(message_sequence, 2147483647), created_at, id
                   ) AS seq
            FROM messages
        )
        UPDATE messages m
        SET conversation_sequence = r.seq
        FROM ranked r
        WHERE m.id = r.id
        """
    )
    op.alter_column("messages", "conversation_sequence", nullable=False)
    op.create_index(
        "uq_messages_conversation_sequence",
        "messages",
        ["business_id", "conversation_id", "conversation_sequence"],
        unique=True,
    )

    # 23: message pagination and lookup indexes
    op.create_index(
        "ix_messages_business_conversation_created",
        "messages",
        ["business_id", "conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_messages_business_provider_message",
        "messages",
        ["business_id", "provider", "provider_message_id"],
    )
    op.create_index(
        "ix_messages_business_campaign",
        "messages",
        ["business_id", "campaign_id"],
    )

    # 27/28/29: visibility, redaction, moderation lifecycle
    op.add_column("messages", sa.Column("visibility", sa.String(length=32), nullable=True))
    op.execute("UPDATE messages SET visibility = 'customer_visible' WHERE visibility IS NULL")
    op.alter_column("messages", "visibility", nullable=False)

    op.add_column("messages", sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("redacted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("redaction_reason", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("contains_pii", sa.Boolean(), nullable=True))
    op.add_column("messages", sa.Column("moderation_status", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("redaction_status", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_messages_redacted_by_user_id",
        "messages",
        "users",
        ["redacted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 21: send-attempt ledger shape + uniqueness
    op.add_column("message_send_attempts", sa.Column("attempt_number", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY business_id, message_id
                       ORDER BY attempted_at, id
                   ) AS rn
            FROM message_send_attempts
        )
        UPDATE message_send_attempts a
        SET attempt_number = ranked.rn
        FROM ranked
        WHERE a.id = ranked.id
        """
    )
    op.alter_column("message_send_attempts", "attempt_number", nullable=False)

    op.alter_column("message_send_attempts", "request_correlation_id", new_column_name="request_id")
    op.alter_column("message_send_attempts", "response_status", new_column_name="response_status_code")

    op.create_index(
        "uq_message_send_attempt_number",
        "message_send_attempts",
        ["business_id", "message_id", "attempt_number"],
        unique=True,
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

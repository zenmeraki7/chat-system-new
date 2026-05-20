"""Conversation service boundary and message ledger hardening

Revision ID: 019_message_and_conversation_boundary_hardening
Revises: 018_conversation_hardening_and_sequences
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019_message_and_conversation_boundary_hardening"
down_revision = "018_conversation_hardening_and_sequences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # conversation nonblank visitor guard
    op.execute(
        "ALTER TABLE conversations ADD CONSTRAINT chk_conversations_visitor_id_nonblank CHECK (btrim(visitor_id) <> '')"
    )

    # message relationship safety / semantics
    op.add_column("messages", sa.Column("provider", sa.String(length=50), nullable=True))
    op.add_column("messages", sa.Column("sender_type", sa.String(length=20), nullable=True))
    op.add_column("messages", sa.Column("message_kind", sa.String(length=30), nullable=True))
    op.add_column("messages", sa.Column("created_from_webhook_event_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("content_text", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.execute("UPDATE messages SET content_text = content WHERE content_text IS NULL")
    op.execute("UPDATE messages SET sender_type = 'contact' WHERE role = 'user' AND sender_type IS NULL")
    op.execute("UPDATE messages SET sender_type = 'bot' WHERE role = 'assistant' AND sender_type IS NULL")
    op.execute("UPDATE messages SET sender_type = 'system' WHERE role = 'system' AND sender_type IS NULL")
    op.execute("UPDATE messages SET message_kind = 'text' WHERE message_kind IS NULL")
    op.execute("UPDATE messages SET status = 'queued' WHERE status IS NULL")

    op.alter_column("messages", "status", existing_type=sa.String(length=30), nullable=False)
    op.alter_column("messages", "sender_type", existing_type=sa.String(length=20), nullable=False)
    op.alter_column("messages", "message_kind", existing_type=sa.String(length=30), nullable=False)

    op.create_foreign_key(
        "fk_messages_created_from_webhook_event_id",
        "messages",
        "webhook_events",
        ["created_from_webhook_event_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # tenant-safe constraints/indexes for provider and idempotency
    op.create_index(
        "uq_messages_provider_message",
        "messages",
        ["business_id", "provider", "provider_message_id"],
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_messages_business_idempotency",
        "messages",
        ["business_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # tighten deletes: no business-history cascade
    op.drop_constraint("fk_messages_conversation_tenant", "messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_messages_conversation_tenant",
        "messages",
        "conversations",
        ["business_id", "conversation_id"],
        ["business_id", "id"],
        ondelete="RESTRICT",
    )

    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_business_id_fkey")
    op.create_foreign_key(
        "messages_business_id_fkey",
        "messages",
        "businesses",
        ["business_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

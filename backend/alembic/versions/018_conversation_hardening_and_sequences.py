"""Conversation identity hardening, tenant-scoped indexes, status migration, and sequencing

Revision ID: 018_conversation_hardening_and_sequences
Revises: 017_operational_safety_and_events
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "018_conversation_hardening_and_sequences"
down_revision = "017_operational_safety_and_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 172/173: convert enum to string, then remap active -> open
    op.execute("ALTER TABLE conversations ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE conversations ALTER COLUMN status TYPE VARCHAR(32) USING status::text")
    op.execute("UPDATE conversations SET status = 'open' WHERE status = 'active'")
    op.execute("DROP TYPE IF EXISTS conversationstatus")
    op.execute(
        "ALTER TABLE conversations ADD CONSTRAINT chk_conversations_status "
        "CHECK (status IN ('open', 'pending', 'resolved', 'closed', 'archived'))"
    )
    op.execute(
        "COMMENT ON TABLE conversations IS "
        "'Tenant-scoped customer interaction thread. Customer identity belongs in contacts/contact_identities.'"
    )
    op.execute("ALTER TABLE conversations ALTER COLUMN status SET DEFAULT 'open'")

    # 176/178: environment + sequence allocator
    op.add_column("conversations", sa.Column("environment", sa.String(length=20), nullable=True))
    op.add_column("conversations", sa.Column("next_message_sequence", sa.Integer(), nullable=True))
    op.execute("UPDATE conversations SET environment = 'live' WHERE environment IS NULL")
    op.execute("UPDATE conversations SET next_message_sequence = 1 WHERE next_message_sequence IS NULL")
    op.alter_column("conversations", "environment", nullable=False)
    op.alter_column("conversations", "next_message_sequence", nullable=False)

    op.add_column("messages", sa.Column("message_sequence", sa.Integer(), nullable=True))

    # 168/167: prefer tenant-scoped indexes
    op.create_index("ix_conversations_business_visitor", "conversations", ["business_id", "visitor_id"])
    op.create_index("ix_conversations_business_status", "conversations", ["business_id", "status"])
    op.create_index(
        "ix_conversations_business_status_last_message",
        "conversations",
        ["business_id", "status", "last_message_at"],
    )
    op.drop_index("ix_conversations_business_id", table_name="conversations")

    # 171/170: identity safety and verification lifecycle
    op.add_column("contact_identities", sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("contact_identities", sa.Column("provider", sa.String(length=40), nullable=True))
    op.add_column("contact_identities", sa.Column("provider_identity_type", sa.String(length=40), nullable=True))
    op.add_column("contact_identities", sa.Column("provider_identity_id", sa.String(length=255), nullable=True))
    op.add_column("contact_identities", sa.Column("verification_status", sa.String(length=20), nullable=True))
    op.add_column("contact_identities", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE contact_identities SET verification_status = 'unverified' WHERE verification_status IS NULL")
    op.alter_column("contact_identities", "verification_status", nullable=False)
    op.create_foreign_key(
        "fk_contact_identities_channel_id",
        "contact_identities",
        "channels",
        ["channel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_contact_provider_identity",
        "contact_identities",
        ["business_id", "channel_id", "identity_type", "identity_value_hash"],
        unique=True,
    )
    op.create_index(
        "uq_contact_provider_identity_external",
        "contact_identities",
        ["business_id", "provider", "provider_identity_type", "provider_identity_id"],
        unique=True,
        postgresql_where=sa.text("provider IS NOT NULL AND provider_identity_id IS NOT NULL"),
    )

    # 169: move trusted naming to contacts, visitor_name remains unverified metadata
    op.add_column("contacts", sa.Column("display_name_source", sa.String(length=40), nullable=True))
    op.add_column("contacts", sa.Column("display_name_verified_at", sa.DateTime(timezone=True), nullable=True))

    # 176: isolate test traffic at channel level
    op.add_column("channels", sa.Column("environment", sa.String(length=20), nullable=True))
    op.execute("UPDATE channels SET environment = 'live' WHERE environment IS NULL")
    op.alter_column("channels", "environment", nullable=False)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

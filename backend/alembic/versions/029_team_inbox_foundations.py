"""Add team inbox foundational tables and SLA due fields

Revision ID: 029_team_inbox_foundations
Revises: 028_whatsapp_onboarding_metadata_fields
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "029_team_inbox_foundations"
down_revision = "028_whatsapp_onboarding_metadata_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("first_response_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_conversations_first_response_due_at", "conversations", ["first_response_due_at"])
    op.create_index("ix_conversations_resolution_due_at", "conversations", ["resolution_due_at"])

    op.create_table(
        "inboxes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("channel_type", sa.String(length=40), nullable=False, server_default="omni"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inboxes_business_id", "inboxes", ["business_id"])

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="offline"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agents_business_id", "agents", ["business_id"])
    op.create_index("ix_agents_user_id", "agents", ["user_id"])

    op.create_table(
        "internal_note_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("internal_note_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("internal_notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mentioned_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mention_text", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_internal_note_mentions_internal_note_id", "internal_note_mentions", ["internal_note_id"])
    op.create_index("ix_internal_note_mentions_mentioned_user_id", "internal_note_mentions", ["mentioned_user_id"])

    op.create_table(
        "conversation_typing_presence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="typing"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_typing_presence_conversation_id", "conversation_typing_presence", ["conversation_id"])
    op.create_index("ix_conversation_typing_presence_business_id", "conversation_typing_presence", ["business_id"])
    op.create_index("ix_conversation_typing_presence_user_id", "conversation_typing_presence", ["user_id"])
    op.create_index("ix_conversation_typing_presence_expires_at", "conversation_typing_presence", ["expires_at"])

    op.create_table(
        "conversation_saved_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("visibility", sa.String(length=30), nullable=False, server_default="private"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_saved_views_business_id", "conversation_saved_views", ["business_id"])
    op.create_index("ix_conversation_saved_views_owner_user_id", "conversation_saved_views", ["owner_user_id"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")


"""Message AI provenance, redaction hashes, moderation, and search documents

Revision ID: 024_message_provenance_and_moderation
Revises: 023_message_template_snapshot_and_events
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "024_message_provenance_and_moderation"
down_revision = "023_message_template_snapshot_and_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("ai_response_id", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("prompt_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("knowledge_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("model_name", sa.String(length=120), nullable=True))
    op.add_column("messages", sa.Column("safety_status", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("handoff_decision", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("content_redacted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("content_redaction_reason", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("content_hash", sa.String(length=128), nullable=True))
    op.add_column("messages", sa.Column("provider_payload_redacted_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("messages", sa.Column("provider_payload_hash", sa.String(length=128), nullable=True))
    op.add_column("messages", sa.Column("raw_payload_retention_until", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_messages_prompt_version_id",
        "messages",
        "ai_prompt_versions",
        ["prompt_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_messages_knowledge_snapshot_id",
        "messages",
        "knowledge_sync_runs",
        ["knowledge_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_messages_ai_response_id", "messages", ["ai_response_id"])
    op.create_index("ix_messages_prompt_version_id", "messages", ["prompt_version_id"])
    op.create_index("ix_messages_knowledge_snapshot_id", "messages", ["knowledge_snapshot_id"])
    op.create_index("ix_messages_content_hash", "messages", ["content_hash"])
    op.create_index("ix_messages_provider_payload_hash", "messages", ["provider_payload_hash"])

    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT chk_messages_content_text_len "
        "CHECK (content_text IS NULL OR char_length(content_text) <= 8192)"
    )
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT chk_messages_rendered_preview_text_len "
        "CHECK (rendered_preview_text IS NULL OR char_length(rendered_preview_text) <= 8192)"
    )

    op.create_table(
        "message_moderation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("moderation_status", sa.String(length=40), nullable=False),
        sa.Column("categories_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_moderation_results_business_id", "message_moderation_results", ["business_id"])
    op.create_index("ix_message_moderation_results_message_id", "message_moderation_results", ["message_id"])
    op.create_index("ix_message_moderation_results_moderation_status", "message_moderation_results", ["moderation_status"])

    op.create_table(
        "message_search_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("search_document", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_search_documents_business_id", "message_search_documents", ["business_id"])
    op.create_index("uq_message_search_documents_message_id", "message_search_documents", ["message_id"], unique=True)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

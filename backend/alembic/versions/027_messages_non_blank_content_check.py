"""Enforce non-blank message content when present

Revision ID: 027_messages_non_blank_content_check
Revises: 026_message_provenance_grouping_and_webhook_linkage
Create Date: 2026-05-19
"""

from alembic import op


revision = "027_messages_non_blank_content_check"
down_revision = "026_message_provenance_grouping_and_webhook_linkage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE messages SET content = NULL WHERE content IS NOT NULL AND btrim(content) = ''")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT chk_messages_content_not_blank "
        "CHECK (content IS NULL OR btrim(content) <> '')"
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")
